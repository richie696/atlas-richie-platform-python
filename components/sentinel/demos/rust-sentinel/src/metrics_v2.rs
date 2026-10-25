//! Bounded Metrics V2 producer adapter for the demo HTTP boundary.
//!
//! Request handling performs only short in-memory aggregation. Snapshot
//! transport, TLS, ACK validation, and retries live on a background task.

use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    env,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tokio::{
    sync::Notify,
    time::{interval, timeout, MissedTickBehavior},
};
use url::Url;
use uuid::Uuid;

const PROTOCOL: &str = "atlas-richie.metrics/v2";
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;
const MAX_DECIMAL_INTEGER: u128 = 10u128.pow(38) - 1;
const MAX_SNAPSHOT_BYTES: usize = 65_536;
const BOUNDARIES_NS: [u64; 12] = [
    1_000_000,
    5_000_000,
    10_000_000,
    25_000_000,
    50_000_000,
    100_000_000,
    250_000_000,
    500_000_000,
    1_000_000_000,
    2_000_000_000,
    5_000_000_000,
    10_000_000_000,
];

#[derive(Default)]
struct HttpTotals {
    completed: u64,
    admitted: u64,
    blocked: u64,
    business_completed: u64,
    buckets: [u64; 13],
    sample_count: u64,
    total_ns: u128,
    min_ns: Option<u64>,
    max_ns: Option<u64>,
}

#[derive(Serialize)]
struct Counter {
    name: &'static str,
    value: u64,
}

#[derive(Serialize)]
struct Histogram {
    name: &'static str,
    boundaries_ns: &'static [u64; 12],
    bucket_counts: [u64; 13],
    sample_count: u64,
    total_ns: String,
    min_ns: Option<u64>,
    max_ns: Option<u64>,
}

#[derive(Serialize)]
struct Gauge {
    name: &'static str,
    value: Option<f64>,
    quality: &'static str,
}

#[derive(Serialize)]
struct Snapshot {
    protocol_version: &'static str,
    reporter_id: String,
    startup_epoch: String,
    sequence: u64,
    captured_at: String,
    capture_elapsed_ns: String,
    counters: [Counter; 4],
    histograms: Vec<Histogram>,
    gauges: [Gauge; 3],
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DurableReceipt {
    protocol_version: String,
    reporter_id: String,
    startup_epoch: String,
    sequence: u64,
    body_sha256: String,
    received_at: String,
}

struct Capture {
    started: Instant,
    sequence: u64,
    totals: HttpTotals,
}

/// Owns the bounded in-process producer state and its async Collector task.
pub struct MetricsV2Reporter {
    reporter_id: String,
    startup_epoch: String,
    capture: Arc<Mutex<Capture>>,
    acknowledged_sequence: AtomicU64,
    acknowledgement: Notify,
    client: Client,
    endpoint: Url,
}

impl MetricsV2Reporter {
    /// Configure a reporter only when Collector reporting is explicitly enabled.
    pub fn from_environment(startup_epoch: &str) -> Result<Option<Self>, String> {
        let collector_url = match env::var("METRICS_COLLECTOR_URL") {
            Ok(value) if !value.trim().is_empty() => value,
            _ => return Ok(None),
        };
        let reporter_id = env::var("METRICS_REPORTER_ID")
            .map_err(|_| "Metrics V2 reporter identity is required when reporting is enabled")?;
        if reporter_id.trim().is_empty()
            || reporter_id.trim() != reporter_id
            || reporter_id.len() > 200
            || reporter_id.contains(['\r', '\n'])
        {
            return Err("Metrics V2 reporter identity is invalid".into());
        }
        Uuid::parse_str(startup_epoch).map_err(|_| "Metrics V2 process epoch is invalid")?;
        let (client, mut endpoint) = crate::reporting::reporting_client_from_environment()
            .map_err(|_| "Metrics V2 mTLS transport configuration is unavailable or invalid")?;
        if collector_url.trim() != endpoint.as_str().trim_end_matches('/') {
            return Err("Metrics V2 Collector URL is invalid".into());
        }
        endpoint.set_path("/api/reporting/v2/snapshots");
        Ok(Some(Self {
            reporter_id,
            startup_epoch: startup_epoch.to_owned(),
            capture: Arc::new(Mutex::new(Capture {
                started: Instant::now(),
                sequence: 0,
                totals: HttpTotals::default(),
            })),
            acknowledged_sequence: AtomicU64::new(0),
            acknowledgement: Notify::new(),
            client,
            endpoint,
        }))
    }

    /// Record one bounded HTTP outcome; never waits for Collector capacity or I/O.
    pub fn record_http_response(
        &self,
        completed: bool,
        admitted: bool,
        blocked: bool,
        business_completed: bool,
        elapsed: Duration,
    ) {
        let Ok(mut capture) = self.capture.lock() else {
            return;
        };
        let totals = &mut capture.totals;
        let mut valid = true;
        if admitted {
            valid &= increment(&mut totals.admitted);
        }
        if blocked {
            valid &= increment(&mut totals.blocked);
        }
        if completed {
            valid &= increment(&mut totals.completed);
            if business_completed {
                valid &= increment(&mut totals.business_completed);
            }
            valid &= increment(&mut totals.sample_count);
            let nanos = u64::try_from(elapsed.as_nanos()).unwrap_or(u64::MAX);
            let bucket = BOUNDARIES_NS
                .iter()
                .position(|boundary| nanos <= *boundary)
                .unwrap_or(BOUNDARIES_NS.len());
            valid &= increment(&mut totals.buckets[bucket]);
            let Some(total) = totals.total_ns.checked_add(u128::from(nanos)) else {
                return;
            };
            if total > MAX_DECIMAL_INTEGER {
                return;
            }
            totals.total_ns = total;
            totals.min_ns = Some(totals.min_ns.map_or(nanos, |current| current.min(nanos)));
            totals.max_ns = Some(totals.max_ns.map_or(nanos, |current| current.max(nanos)));
        }
        if !valid {
            // Counters stop at their frozen cross-language safe integer ceiling.
            eprintln!(
                "Metrics V2 counter reached its safe limit; further increments are unavailable"
            );
        }
    }

    /// Start one serial background sender. Only one unacknowledged snapshot is retained.
    pub fn start(self: &Arc<Self>) {
        let reporter = Arc::clone(self);
        tokio::spawn(async move { reporter.run().await });
    }

    /// Wait for a specific durable receipt; used by disposable acceptance probes.
    // The production demo intentionally sends asynchronously; only the separate
    // cross-process acceptance example needs to block for its final assertion.
    #[allow(dead_code)]
    pub async fn wait_for_acknowledgement(&self, sequence: u64, wait: Duration) -> bool {
        timeout(wait, async {
            loop {
                let notified = self.acknowledgement.notified();
                if self.acknowledged_sequence.load(Ordering::Acquire) >= sequence {
                    return;
                }
                notified.await;
            }
        })
        .await
        .is_ok()
    }

    fn snapshot(&self) -> Result<(Vec<u8>, u64), String> {
        let mut capture = self
            .capture
            .lock()
            .map_err(|_| "Metrics V2 capture unavailable")?;
        if capture.sequence >= MAX_SAFE_INTEGER {
            return Err("Metrics V2 sequence exhausted".into());
        }
        capture.sequence += 1;
        let sequence = capture.sequence;
        let elapsed = capture.started.elapsed().as_nanos();
        if elapsed > MAX_DECIMAL_INTEGER {
            return Err("Metrics V2 elapsed time exhausted".into());
        }
        let totals = &capture.totals;
        let snapshot = Snapshot {
            protocol_version: PROTOCOL,
            reporter_id: self.reporter_id.clone(),
            startup_epoch: self.startup_epoch.clone(),
            sequence,
            captured_at: utc_micros(),
            capture_elapsed_ns: elapsed.to_string(),
            counters: [
                Counter {
                    name: "http_requests_completed_total",
                    value: totals.completed,
                },
                Counter {
                    name: "sentinel_entries_admitted_total",
                    value: totals.admitted,
                },
                Counter {
                    name: "sentinel_entries_blocked_total",
                    value: totals.blocked,
                },
                Counter {
                    name: "business_transactions_completed_total",
                    value: totals.business_completed,
                },
            ],
            histograms: if totals.sample_count == 0 {
                Vec::new()
            } else {
                vec![Histogram {
                    name: "http_request_duration",
                    boundaries_ns: &BOUNDARIES_NS,
                    bucket_counts: totals.buckets,
                    sample_count: totals.sample_count,
                    total_ns: totals.total_ns.to_string(),
                    min_ns: totals.min_ns,
                    max_ns: totals.max_ns,
                }]
            },
            gauges: [
                Gauge {
                    name: "process_cpu_ratio",
                    value: None,
                    quality: "unavailable",
                },
                Gauge {
                    name: "process_rss_bytes",
                    value: None,
                    quality: "unavailable",
                },
                Gauge {
                    name: "process_memory_ratio",
                    value: None,
                    quality: "unavailable",
                },
            ],
        };
        let bytes =
            serde_json::to_vec(&snapshot).map_err(|_| "Metrics V2 snapshot encoding failed")?;
        if bytes.len() > MAX_SNAPSHOT_BYTES {
            return Err("Metrics V2 snapshot exceeds the protocol size limit".into());
        }
        Ok((bytes, sequence))
    }

    async fn run(self: Arc<Self>) {
        let mut ticker = interval(Duration::from_secs(1));
        ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);
        let mut pending: Option<(Vec<u8>, u64)> = None;
        loop {
            ticker.tick().await;
            if pending.is_none() {
                match self.snapshot() {
                    Ok(snapshot) => pending = Some(snapshot),
                    Err(_) => {
                        eprintln!("Metrics V2 snapshot unavailable");
                        continue;
                    }
                }
            }
            if let Some((body, sequence)) = pending.as_ref() {
                if self.deliver(body, *sequence).await {
                    pending = None;
                }
            }
        }
    }

    async fn deliver(&self, body: &[u8], sequence: u64) -> bool {
        let digest = format!("{:x}", Sha256::digest(body));
        let response = self
            .client
            .post(self.endpoint.clone())
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .body(body.to_vec())
            .send()
            .await;
        let Ok(response) = response else {
            eprintln!("Metrics V2 transport unavailable; exact snapshot retained for retry");
            return false;
        };
        if response.status() != StatusCode::OK {
            eprintln!(
                "Metrics V2 durable ACK rejected; response_status={}",
                response.status().as_u16()
            );
            return false;
        }
        let mut response = response;
        let mut bytes = Vec::new();
        loop {
            match response.chunk().await {
                Ok(Some(chunk)) if bytes.len() + chunk.len() <= MAX_SNAPSHOT_BYTES => {
                    bytes.extend_from_slice(&chunk);
                }
                Ok(Some(_)) => {
                    eprintln!("Metrics V2 durable ACK exceeds the protocol size limit");
                    return false;
                }
                Ok(None) => break,
                Err(_) => {
                    eprintln!(
                        "Metrics V2 durable ACK unreadable; exact snapshot retained for retry"
                    );
                    return false;
                }
            }
        }
        let accepted = valid_durable_receipt(
            &bytes,
            &self.reporter_id,
            &self.startup_epoch,
            sequence,
            &digest,
        );
        if accepted {
            self.acknowledged_sequence
                .store(sequence, Ordering::Release);
            self.acknowledgement.notify_one();
        }
        accepted
    }
}

fn valid_durable_receipt(
    body: &[u8],
    reporter_id: &str,
    startup_epoch: &str,
    sequence: u64,
    body_sha256: &str,
) -> bool {
    let Ok(receipt) = serde_json::from_slice::<DurableReceipt>(body) else {
        return false;
    };
    receipt.protocol_version == PROTOCOL
        && receipt.reporter_id == reporter_id
        && receipt.startup_epoch == startup_epoch
        && receipt.sequence == sequence
        && receipt.body_sha256 == body_sha256
        && valid_utc_micros(&receipt.received_at)
}

fn increment(value: &mut u64) -> bool {
    if *value >= MAX_SAFE_INTEGER {
        return false;
    }
    *value += 1;
    true
}

fn utc_micros() -> String {
    use time::OffsetDateTime;
    let format = time::format_description::parse_borrowed::<3>(
        "[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:6]Z",
    );
    let now = OffsetDateTime::now_utc();
    let formatted = match format {
        Ok(format) => now.format(&format),
        Err(_) => now.format(&time::format_description::well_known::Rfc3339),
    };
    formatted.unwrap_or_else(|_| "1970-01-01T00:00:00.000000Z".into())
}

fn valid_utc_micros(value: &str) -> bool {
    value.len() == 27
        && value.as_bytes().get(4) == Some(&b'-')
        && value.as_bytes().get(7) == Some(&b'-')
        && value.as_bytes().get(10) == Some(&b'T')
        && value.as_bytes().get(13) == Some(&b':')
        && value.as_bytes().get(16) == Some(&b':')
        && value.as_bytes().get(19) == Some(&b'.')
        && value.as_bytes().get(26) == Some(&b'Z')
        && value.bytes().enumerate().all(|(index, byte)| {
            matches!(index, 4 | 7 | 10 | 13 | 16 | 19 | 26) || byte.is_ascii_digit()
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn reporter() -> MetricsV2Reporter {
        MetricsV2Reporter {
            reporter_id: "rust-worker-0".into(),
            startup_epoch: "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db".into(),
            capture: Arc::new(Mutex::new(Capture {
                started: Instant::now(),
                sequence: 0,
                totals: HttpTotals::default(),
            })),
            acknowledged_sequence: AtomicU64::new(0),
            acknowledgement: Notify::new(),
            client: Client::new(),
            endpoint: Url::parse("https://collector.example").unwrap(),
        }
    }

    #[test]
    fn snapshot_uses_frozen_metrics_v2_semantics_and_unavailable_process_gauges() {
        let reporter = reporter();
        reporter.record_http_response(true, true, false, true, Duration::from_millis(5));
        reporter.record_http_response(true, false, true, false, Duration::from_millis(11));
        let (bytes, sequence) = reporter.snapshot().unwrap();
        let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(sequence, 1);
        assert_eq!(value["protocol_version"], PROTOCOL);
        assert_eq!(value["reporter_id"], "rust-worker-0");
        assert_eq!(value["startup_epoch"], reporter.startup_epoch);
        assert_eq!(value["counters"][0]["value"], 2);
        assert_eq!(value["counters"][1]["value"], 1);
        assert_eq!(value["counters"][2]["value"], 1);
        assert_eq!(value["counters"][3]["value"], 1);
        assert_eq!(value["histograms"][0]["sample_count"], 2);
        assert_eq!(
            value["histograms"][0]["bucket_counts"]
                .as_array()
                .unwrap()
                .len(),
            13
        );
        assert_eq!(value["gauges"][0]["quality"], "unavailable");
        assert!(value["gauges"][0]["value"].is_null());
    }

    #[test]
    fn empty_snapshot_has_no_histogram_and_ack_time_is_strict() {
        let reporter = reporter();
        let (bytes, _) = reporter.snapshot().unwrap();
        let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(value["histograms"], serde_json::json!([]));
        assert!(valid_utc_micros("2026-10-17T08:09:10.123456Z"));
        assert!(!valid_utc_micros("2026-10-17T08:09:10.123Z"));
    }

    #[test]
    fn durable_ack_must_correlate_exact_snapshot_and_reject_extra_or_duplicate_fields() {
        let valid = serde_json::json!({
            "protocol_version": PROTOCOL,
            "reporter_id": "rust-worker-0",
            "startup_epoch": "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db",
            "sequence": 7,
            "body_sha256": "a".repeat(64),
            "received_at": "2026-10-17T08:09:10.123456Z"
        });
        let bytes = serde_json::to_vec(&valid).unwrap();
        assert!(valid_durable_receipt(
            &bytes,
            "rust-worker-0",
            "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db",
            7,
            &"a".repeat(64),
        ));
        assert!(!valid_durable_receipt(
            &bytes,
            "rust-worker-0",
            "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db",
            8,
            &"a".repeat(64),
        ));
        let with_unknown = br#"{"protocol_version":"atlas-richie.metrics/v2","reporter_id":"rust-worker-0","startup_epoch":"b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db","sequence":7,"body_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","received_at":"2026-10-17T08:09:10.123456Z","extra":true}"#;
        assert!(!valid_durable_receipt(
            with_unknown,
            "rust-worker-0",
            "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db",
            7,
            &"a".repeat(64),
        ));
        let duplicate = br#"{"protocol_version":"atlas-richie.metrics/v2","reporter_id":"rust-worker-0","startup_epoch":"b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db","sequence":7,"sequence":7,"body_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","received_at":"2026-10-17T08:09:10.123456Z"}"#;
        assert!(!valid_durable_receipt(
            duplicate,
            "rust-worker-0",
            "b2bc2b8a-17f4-4d66-ae6f-f21c1f4ac4db",
            7,
            &"a".repeat(64),
        ));
    }
}
