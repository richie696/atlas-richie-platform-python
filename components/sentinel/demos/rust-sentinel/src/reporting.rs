use crate::{rules::ManagedPublication, source::RuleSnapshot};
use reqwest::{Certificate, Client, Identity, StatusCode};
use serde::Serialize;
use std::{
    env, fs,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    sync::{mpsc, Notify},
    time::{sleep, timeout},
};
use url::Url;
use uuid::Uuid;

const OBSERVATION_PROTOCOL: &str = "atlas-richie.sentinel.rule-load-observation/v1";
const RECEIPT_PROTOCOL: &str = "atlas-richie.sentinel.rule-publication-receipt/v1";

#[derive(Clone)]
pub struct AppliedFacts {
    pub source_bytes_sha256: String,
    pub canonical_rules_sha256: String,
    pub member_fingerprints: Vec<String>,
}

#[derive(Clone, Serialize)]
struct ObservationMember {
    rule_kind: &'static str,
    fingerprint_sha256: String,
}

#[derive(Clone, Serialize)]
struct ActiveSnapshotBody {
    source_revision: Option<String>,
    source_bytes_sha256: Option<String>,
    canonical_rules_sha256: String,
    membership_complete: bool,
    members: Vec<ObservationMember>,
}

#[derive(Serialize)]
struct AttemptBody {
    source_revision: Option<String>,
    source_bytes_sha256: Option<String>,
    canonical_rules_sha256: Option<String>,
    failure_reason: &'static str,
}

#[derive(Serialize)]
struct ObservationBody {
    protocol_version: &'static str,
    observation_id: String,
    process_epoch: String,
    sequence: u64,
    binding_id: String,
    profile_id: String,
    event_kind: &'static str,
    active_snapshot: Option<ActiveSnapshotBody>,
    attempt: Option<AttemptBody>,
    observed_at: String,
}

struct SequenceState {
    next: u64,
    latest: Option<ActiveSnapshotBody>,
}

/// Bounded, nonblocking producer adapter for the Rule Load Observation V1 port.
pub struct RuleLoadReporter {
    sender: mpsc::Sender<QueuedReport>,
    state: Mutex<SequenceState>,
    receipt_sequence: Mutex<u64>,
    acknowledgements: Arc<Acknowledgements>,
    epoch: String,
    binding_id: String,
    profile_id: String,
}

#[derive(Clone, Copy)]
enum ReportEndpoint {
    Observation,
    PublicationReceipt,
}

struct QueuedReport {
    endpoint: ReportEndpoint,
    sequence: u64,
    body: Vec<u8>,
}

#[derive(Default)]
struct Acknowledgements {
    observation_sequence: AtomicU64,
    receipt_sequence: AtomicU64,
    changed: Notify,
}

#[derive(Serialize)]
struct PublicationReceiptBody {
    protocol_version: &'static str,
    receipt_id: String,
    process_epoch: String,
    sequence: u64,
    binding_id: String,
    publication_id: String,
    target_version_id: String,
    target_payload_sha256: String,
    state: &'static str,
    reason: Option<&'static str>,
    source_revision: Option<String>,
    observed_at: String,
}

impl RuleLoadReporter {
    pub fn from_environment(epoch: String) -> Result<Option<Self>, String> {
        let binding_id = env::var("RULE_BINDING_ID").unwrap_or_default();
        if binding_id.trim().is_empty() {
            return Ok(None);
        }
        if !valid_identifier(&binding_id) {
            return Err("rule observation binding identity is invalid".into());
        }
        let profile_id = env::var("RULE_PROFILE_ID").unwrap_or_else(|_| "sentinel-rust-v1".into());
        if !valid_identifier(&profile_id) {
            return Err("rule observation profile identity is invalid".into());
        }
        let (client, base_url) = reporting_client_from_environment()?;
        Uuid::parse_str(&epoch).map_err(|_| "rule observation process epoch is invalid")?;
        let (sender, receiver) = mpsc::channel::<QueuedReport>(128);
        let acknowledgements = Arc::new(Acknowledgements::default());
        tokio::spawn(run_observation_transport(
            client,
            base_url,
            receiver,
            Arc::clone(&acknowledgements),
        ));
        Ok(Some(Self {
            sender,
            state: Mutex::new(SequenceState {
                next: 0,
                latest: None,
            }),
            receipt_sequence: Mutex::new(0),
            acknowledgements,
            epoch,
            binding_id,
            profile_id,
        }))
    }

    /// Wait for durable Collector acknowledgements; used only by disposable acceptance probes.
    #[allow(dead_code)]
    pub async fn wait_for_durable_acknowledgements(
        &self,
        observation_sequence: u64,
        publication_receipt_sequence: u64,
        wait: Duration,
    ) -> bool {
        timeout(wait, async {
            loop {
                let notified = self.acknowledgements.changed.notified();
                let observation_acknowledged = self
                    .acknowledgements
                    .observation_sequence
                    .load(Ordering::Acquire)
                    >= observation_sequence;
                let receipt_acknowledged = self
                    .acknowledgements
                    .receipt_sequence
                    .load(Ordering::Acquire)
                    >= publication_receipt_sequence;
                if observation_acknowledged && receipt_acknowledged {
                    return;
                }
                notified.await;
            }
        })
        .await
        .is_ok()
    }

    pub fn applied(
        &self,
        source: &RuleSnapshot,
        facts: &AppliedFacts,
        managed: Option<&ManagedPublication>,
    ) {
        let snapshot = ActiveSnapshotBody {
            source_revision: Some(source.revision.clone()),
            source_bytes_sha256: Some(facts.source_bytes_sha256.clone()),
            canonical_rules_sha256: facts.canonical_rules_sha256.clone(),
            membership_complete: true,
            members: facts
                .member_fingerprints
                .iter()
                .cloned()
                .map(|fingerprint_sha256| ObservationMember {
                    rule_kind: "flow",
                    fingerprint_sha256,
                })
                .collect(),
        };
        if let Ok(mut state) = self.state.lock() {
            state.latest = Some(snapshot.clone());
            self.enqueue_locked(&mut state, "snapshot_applied", Some(snapshot), None);
        }
        if let Some(publication) = managed {
            self.enqueue_receipt(source, publication);
        }
    }

    pub fn failed(&self, reason: &'static str) {
        if !matches!(
            reason,
            "source_unavailable"
                | "decode_rejected"
                | "profile_unsupported"
                | "validation_rejected"
                | "apply_failed"
        ) {
            return;
        }
        if let Ok(mut state) = self.state.lock() {
            let latest = state.latest.clone();
            self.enqueue_locked(
                &mut state,
                "snapshot_failed",
                latest,
                Some(AttemptBody {
                    source_revision: None,
                    source_bytes_sha256: None,
                    canonical_rules_sha256: None,
                    failure_reason: reason,
                }),
            );
        }
    }

    pub fn heartbeat(&self) {
        if let Ok(mut state) = self.state.lock() {
            let latest = state.latest.clone();
            self.enqueue_locked(&mut state, "heartbeat", latest, None);
        }
    }

    fn enqueue_locked(
        &self,
        state: &mut SequenceState,
        event_kind: &'static str,
        active_snapshot: Option<ActiveSnapshotBody>,
        attempt: Option<AttemptBody>,
    ) {
        if state.next >= 9_007_199_254_740_991 {
            return;
        }
        state.next += 1;
        let body = ObservationBody {
            protocol_version: OBSERVATION_PROTOCOL,
            observation_id: Uuid::new_v4().to_string(),
            process_epoch: self.epoch.clone(),
            sequence: state.next,
            binding_id: self.binding_id.clone(),
            profile_id: self.profile_id.clone(),
            event_kind,
            active_snapshot,
            attempt,
            observed_at: chrono_like_utc_millis(),
        };
        let Ok(bytes) = serde_json::to_vec(&body) else {
            return;
        };
        if bytes.len() > 512 * 1024
            || self
                .sender
                .try_send(QueuedReport {
                    endpoint: ReportEndpoint::Observation,
                    sequence: state.next,
                    body: bytes,
                })
                .is_err()
        {
            eprintln!(
                "Rule Load Observation queue full or encoding unavailable; event not retained"
            );
        }
    }

    fn enqueue_receipt(&self, source: &RuleSnapshot, publication: &ManagedPublication) {
        let Ok(mut sequence) = self.receipt_sequence.lock() else {
            return;
        };
        if *sequence >= 9_007_199_254_740_991 {
            return;
        }
        *sequence += 1;
        let (binding_id, _, _) = publication.tuple();
        let body = PublicationReceiptBody {
            protocol_version: RECEIPT_PROTOCOL,
            receipt_id: Uuid::new_v4().to_string(),
            process_epoch: self.epoch.clone(),
            sequence: *sequence,
            binding_id: binding_id.into(),
            publication_id: publication.publication_id().into(),
            target_version_id: publication.target_version_id().into(),
            target_payload_sha256: publication.payload_sha256().into(),
            state: "applied",
            reason: None,
            source_revision: Some(source.revision.clone()),
            observed_at: chrono_like_utc_millis(),
        };
        let Ok(body) = serde_json::to_vec(&body) else {
            return;
        };
        if body.len() > 16 * 1024
            || self
                .sender
                .try_send(QueuedReport {
                    endpoint: ReportEndpoint::PublicationReceipt,
                    sequence: *sequence,
                    body,
                })
                .is_err()
        {
            eprintln!(
                "Rule Publication Receipt queue full or encoding unavailable; receipt not retained"
            );
        }
    }
}

async fn run_observation_transport(
    client: Client,
    base_url: Url,
    mut receiver: mpsc::Receiver<QueuedReport>,
    acknowledgements: Arc<Acknowledgements>,
) {
    let negotiation_url =
        match base_url.join("/api/reporting/v1/protocol-negotiations/rule-load-observation") {
            Ok(url) => url,
            Err(_) => return,
        };
    let observation_url = match base_url.join("/api/reporting/v1/rule-load-observations") {
        Ok(url) => url,
        Err(_) => return,
    };
    let mut compatible = false;
    loop {
        tokio::select! {
            event = receiver.recv() => {
                let Some(event) = event else { return; };
                let endpoint = match event.endpoint {
                    ReportEndpoint::Observation => observation_url.clone(),
                    ReportEndpoint::PublicationReceipt => match base_url.join("/api/reporting/v1/rule-publication-receipts") {
                        Ok(url) => url,
                        Err(_) => continue,
                    },
                };
                loop {
                    if matches!(event.endpoint, ReportEndpoint::Observation) && !compatible {
                        compatible = negotiate(&client, &negotiation_url).await;
                        if !compatible {
                            sleep(Duration::from_secs(2)).await;
                            continue;
                        }
                    }
                    match client.post(endpoint.clone()).header("Content-Type", "application/json").body(event.body.clone()).send().await {
                        Ok(response) if response.status() == StatusCode::NO_CONTENT => {
                            let sequence = match event.endpoint {
                                ReportEndpoint::Observation => &acknowledgements.observation_sequence,
                                ReportEndpoint::PublicationReceipt => &acknowledgements.receipt_sequence,
                            };
                            sequence.fetch_max(event.sequence, Ordering::AcqRel);
                            acknowledgements.changed.notify_one();
                            break;
                        },
                        Ok(response) => eprintln!("Runtime reporting Collector rejected event; status={}", response.status().as_u16()),
                        Err(_) => eprintln!("Runtime reporting Collector unavailable; exact event retained for retry"),
                    }
                    sleep(Duration::from_secs(1)).await;
                }
            }
        }
    }
}

async fn negotiate(client: &Client, endpoint: &Url) -> bool {
    let body = serde_json::json!({"protocol_version": OBSERVATION_PROTOCOL});
    let Ok(response) = client.post(endpoint.clone()).json(&body).send().await else {
        return false;
    };
    if response.status() != StatusCode::OK {
        return false;
    }
    let Ok(result) = response.json::<serde_json::Value>().await else {
        return false;
    };
    result.get("protocol_version").and_then(|v| v.as_str())
        == Some("atlas-richie.protocol-negotiation/v1")
        && result.get("boundary").and_then(|v| v.as_str()) == Some("rule-load-observation")
        && result.get("compatibility").and_then(|v| v.as_str()) == Some("compatible")
        && result
            .get("collector_supported")
            .and_then(|v| v.as_array())
            .is_some_and(|supported| {
                supported
                    .iter()
                    .any(|item| item.as_str() == Some(OBSERVATION_PROTOCOL))
            })
}

pub(crate) fn reporting_client_from_environment() -> Result<(Client, Url), String> {
    let collector_url = env::var("METRICS_COLLECTOR_URL")
        .map_err(|_| "rule reporting requires the enrolled mTLS Collector transport")?;
    let base_url = Url::parse(&collector_url).map_err(|_| "Collector URL is invalid")?;
    if base_url.scheme() != "https"
        || base_url.host_str().is_none()
        || base_url.username() != ""
        || base_url.password().is_some()
        || base_url.query().is_some()
        || base_url.fragment().is_some()
        || !matches!(base_url.path(), "" | "/")
    {
        return Err("Collector URL must be an HTTPS origin".into());
    }
    let certificate_path =
        env::var("METRICS_CLIENT_CERT").map_err(|_| "mTLS client certificate is required")?;
    let key_path = env::var("METRICS_CLIENT_KEY").map_err(|_| "mTLS client key is required")?;
    let ca_path = env::var("METRICS_COLLECTOR_CA").map_err(|_| "Collector CA is required")?;
    let mut identity =
        fs::read(certificate_path).map_err(|_| "mTLS client certificate is unavailable")?;
    identity.extend_from_slice(&fs::read(key_path).map_err(|_| "mTLS client key is unavailable")?);
    let identity = Identity::from_pem(&identity).map_err(|_| "mTLS client identity is invalid")?;
    let ca = Certificate::from_pem(&fs::read(ca_path).map_err(|_| "Collector CA is unavailable")?)
        .map_err(|_| "Collector CA is invalid")?;
    let client = Client::builder()
        .identity(identity)
        .add_root_certificate(ca)
        .timeout(Duration::from_secs(5))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "mTLS reporting transport could not be initialized")?;
    Ok((client, base_url))
}

fn valid_identifier(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 200
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(byte))
}

fn chrono_like_utc_millis() -> String {
    // SystemTime has no formatting API; use the standard RFC3339 UTC format
    // through the pinned time dependency already used by the SDK graph.
    use time::OffsetDateTime;
    let format = time::format_description::parse_borrowed::<3>(
        "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:3]Z",
    );
    let now = OffsetDateTime::now_utc();
    let formatted = match format {
        Ok(format) => now.format(&format),
        Err(_) => now.format(&time::format_description::well_known::Rfc3339),
    };
    formatted.unwrap_or_else(|_| "1970-01-01T00:00:00.000Z".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rules;

    fn reporter(capacity: usize) -> (RuleLoadReporter, mpsc::Receiver<QueuedReport>) {
        let (sender, receiver) = mpsc::channel(capacity);
        (
            RuleLoadReporter {
                sender,
                state: Mutex::new(SequenceState {
                    next: 0,
                    latest: None,
                }),
                receipt_sequence: Mutex::new(0),
                acknowledgements: Arc::new(Acknowledgements::default()),
                epoch: "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db".into(),
                binding_id: "binding-01".into(),
                profile_id: "sentinel-rust-v1".into(),
            },
            receiver,
        )
    }

    #[test]
    fn observation_queue_is_bounded_and_reports_exact_snapshot_facts() {
        let (reporter, mut receiver) = reporter(2);
        let snapshot = RuleSnapshot {
            content: "[]".into(),
            revision: "consul-index-42".into(),
        };
        reporter.applied(
            &snapshot,
            &AppliedFacts {
                source_bytes_sha256: "a".repeat(64),
                canonical_rules_sha256: "b".repeat(64),
                member_fingerprints: Vec::new(),
            },
            None,
        );
        let queued = receiver.try_recv().unwrap();
        assert!(matches!(queued.endpoint, ReportEndpoint::Observation));
        let body: serde_json::Value = serde_json::from_slice(&queued.body).unwrap();
        assert_eq!(body["protocol_version"], OBSERVATION_PROTOCOL);
        assert_eq!(body["observation_id"].as_str().unwrap().len(), 36);
        assert_eq!(
            body["process_epoch"],
            "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db"
        );
        assert_eq!(body["sequence"], 1);
        assert_eq!(body["event_kind"], "snapshot_applied");
        assert_eq!(
            body["active_snapshot"]["source_revision"],
            "consul-index-42"
        );
        assert_eq!(body["active_snapshot"]["membership_complete"], true);
        assert_eq!(body["attempt"], serde_json::Value::Null);
    }

    #[test]
    fn managed_apply_emits_exact_tuple_receipt_without_credentials_or_payload() {
        let (reporter, mut receiver) = reporter(2);
        let payload = r#"[{"resource":"orders","grade":1,"count":2}]"#;
        let digest = rules::sha256_hex(payload.as_bytes());
        let envelope = format!(
            r#"{{"protocol_version":"atlas-richie.sentinel.managed-rule-publication/v1","binding_id":"binding-01","publication_id":"publication-42","target_version_id":"version-42","publication_sequence":42,"rule_kind":"flow","profile_id":"sentinel-rust-v1","payload_sha256":"{digest}","rule_payload":{}}}"#,
            serde_json::to_string(payload).unwrap()
        );
        let (_, managed) =
            rules::decode_managed_flow_envelope(&envelope, "binding-01", "sentinel-rust-v1")
                .unwrap();
        let snapshot = RuleSnapshot {
            content: envelope,
            revision: "nacos-md5-provider-revision".into(),
        };
        reporter.applied(
            &snapshot,
            &AppliedFacts {
                source_bytes_sha256: "a".repeat(64),
                canonical_rules_sha256: "b".repeat(64),
                member_fingerprints: vec!["c".repeat(64)],
            },
            Some(&managed),
        );
        let observation = receiver.try_recv().unwrap();
        assert!(matches!(observation.endpoint, ReportEndpoint::Observation));
        let receipt = receiver.try_recv().unwrap();
        assert!(matches!(
            receipt.endpoint,
            ReportEndpoint::PublicationReceipt
        ));
        let body: serde_json::Value = serde_json::from_slice(&receipt.body).unwrap();
        assert_eq!(body["protocol_version"], RECEIPT_PROTOCOL);
        assert_eq!(body["binding_id"], "binding-01");
        assert_eq!(body["publication_id"], "publication-42");
        assert_eq!(body["target_version_id"], "version-42");
        assert_eq!(body["target_payload_sha256"], digest);
        assert_eq!(body["state"], "applied");
        assert_eq!(body["source_revision"], "nacos-md5-provider-revision");
        assert!(body.get("rule_payload").is_none());
        assert!(body.get("password").is_none());
    }

    #[test]
    fn failed_candidate_event_contains_only_stable_reason() {
        let (reporter, mut receiver) = reporter(1);
        reporter.failed("validation_rejected");
        let queued = receiver.try_recv().unwrap();
        let body: serde_json::Value = serde_json::from_slice(&queued.body).unwrap();
        assert_eq!(body["event_kind"], "snapshot_failed");
        assert_eq!(body["attempt"]["failure_reason"], "validation_rejected");
        assert!(body["attempt"].get("exception").is_none());
    }
}
