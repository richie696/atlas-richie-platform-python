use sentinel_core::flow::{self, CalculateStrategy, ControlStrategy, Rule};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{collections::HashSet, sync::Arc};

const MAX_RULES_BYTES: usize = 500 * 1024;
const MAX_RULES: usize = 1_000;
const MAX_RESOURCE_BYTES: usize = 200;
const MAX_THRESHOLD: f64 = 1_000_000_000.0;
const MANAGED_PROTOCOL: &str = "atlas-richie.sentinel.managed-rule-publication/v1";

#[derive(Clone, Debug, PartialEq)]
pub struct CanonicalFlowRule {
    pub resource: String,
    pub threshold: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ManagedPublication {
    binding_id: String,
    publication_id: String,
    target_version_id: String,
    publication_sequence: u64,
    payload_sha256: String,
}

impl ManagedPublication {
    pub fn tuple(&self) -> (&str, &str, &str) {
        (
            &self.binding_id,
            &self.publication_id,
            &self.target_version_id,
        )
    }

    pub fn publication_id(&self) -> &str {
        &self.publication_id
    }

    pub fn target_version_id(&self) -> &str {
        &self.target_version_id
    }

    pub fn sequence(&self) -> u64 {
        self.publication_sequence
    }

    pub fn payload_sha256(&self) -> &str {
        &self.payload_sha256
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FlowRuleInput {
    resource: String,
    #[serde(default)]
    count: Option<Box<serde_json::value::RawValue>>,
    #[serde(default)]
    threshold: Option<Box<serde_json::value::RawValue>>,
    #[serde(default)]
    grade: Option<u8>,
    #[serde(default)]
    strategy: Option<u8>,
    #[serde(default, rename = "controlBehavior")]
    control_behavior: Option<u8>,
    #[serde(default, rename = "limitApp")]
    limit_app: Option<String>,
    #[serde(default, rename = "warmUpPeriodSec")]
    warm_up_period_sec: Option<u32>,
    #[serde(default, rename = "maxQueueingTimeMs")]
    max_queueing_time_ms: Option<u32>,
    #[serde(default, rename = "clusterMode")]
    cluster_mode: Option<bool>,
    #[serde(default, rename = "refResource")]
    ref_resource: Option<String>,
    #[serde(default, rename = "statIntervalInMs")]
    stat_interval_in_ms: Option<u32>,
    #[serde(default, rename = "tokenCalculateStrategy")]
    token_calculate_strategy: Option<u8>,
    #[serde(default, rename = "relationStrategy")]
    relation_strategy: Option<u8>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ManagedEnvelopeInput {
    protocol_version: String,
    binding_id: String,
    publication_id: String,
    target_version_id: String,
    publication_sequence: u64,
    rule_kind: String,
    profile_id: String,
    payload_sha256: String,
    rule_payload: String,
}

pub fn decode_managed_flow_envelope(
    content: &str,
    expected_binding_id: &str,
    expected_profile_id: &str,
) -> Result<(Vec<CanonicalFlowRule>, ManagedPublication), String> {
    if content.len() > MAX_RULES_BYTES + 16 * 1024 {
        return Err("managed rule envelope exceeds the size limit".into());
    }
    let envelope: ManagedEnvelopeInput = serde_json::from_str(content)
        .map_err(|_| "managed rule envelope is invalid".to_string())?;
    if envelope.protocol_version != MANAGED_PROTOCOL
        || envelope.rule_kind != "flow"
        || envelope.binding_id != expected_binding_id
        || envelope.profile_id != expected_profile_id
        || !valid_identifier(&envelope.binding_id)
        || !valid_identifier(&envelope.publication_id)
        || !valid_identifier(&envelope.target_version_id)
        || envelope.publication_sequence == 0
        || envelope.publication_sequence > 9_007_199_254_740_991
        || envelope.payload_sha256.len() != 64
        || !envelope
            .payload_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || envelope.rule_payload.len() > MAX_RULES_BYTES
    {
        return Err("managed rule envelope is outside the supported profile".into());
    }
    let actual_digest = sha256_hex(envelope.rule_payload.as_bytes());
    let digest_matches = actual_digest
        .as_bytes()
        .iter()
        .zip(envelope.payload_sha256.as_bytes())
        .fold(0_u8, |difference, (left, right)| {
            difference | (left ^ right)
        })
        == 0;
    if !digest_matches {
        return Err("managed rule payload checksum does not match".into());
    }
    let rules = decode_flow_rules(&envelope.rule_payload)?;
    let publication = ManagedPublication {
        binding_id: envelope.binding_id,
        publication_id: envelope.publication_id,
        target_version_id: envelope.target_version_id,
        publication_sequence: envelope.publication_sequence,
        payload_sha256: envelope.payload_sha256,
    };
    Ok((rules, publication))
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

pub fn decode_flow_rules(content: &str) -> Result<Vec<CanonicalFlowRule>, String> {
    if content.trim().is_empty() || content.len() > MAX_RULES_BYTES {
        return Err("rule snapshot is absent or oversized".into());
    }
    let parsed: Vec<FlowRuleInput> = serde_json::from_str(content)
        .map_err(|_| "rule snapshot is not a strict flow-rule array".to_string())?;
    if parsed.len() > MAX_RULES {
        return Err("rule snapshot exceeds the rule count limit".into());
    }
    let mut seen = HashSet::new();
    let mut output = Vec::with_capacity(parsed.len());
    for input in parsed {
        let threshold_number = match (input.count, input.threshold) {
            (Some(value), None) if input.grade.unwrap_or(1) == 1 => value,
            (None, Some(value))
                if input.stat_interval_in_ms.unwrap_or(1_000) == 1_000
                    && input.token_calculate_strategy.unwrap_or(0) == 0
                    && input.relation_strategy.unwrap_or(0) == 0 =>
            {
                value
            }
            _ => return Err("flow rule is outside sentinel-rust-v1 semantics".into()),
        };
        if input.strategy.unwrap_or(0) != 0
            || input.control_behavior.unwrap_or(0) != 0
            || input.limit_app.as_deref().unwrap_or("default") != "default"
            || input.warm_up_period_sec.unwrap_or(0) != 0
            || input.max_queueing_time_ms.unwrap_or(0) != 0
            || input.cluster_mode.unwrap_or(false)
            || !input.ref_resource.as_deref().unwrap_or("").is_empty()
        {
            return Err("flow rule is outside sentinel-rust-v1 semantics".into());
        }
        let threshold = canonical_threshold(threshold_number.get())?;
        if input.resource.is_empty()
            || input.resource.trim() != input.resource
            || input.resource.len() > MAX_RESOURCE_BYTES
            || !seen.insert(input.resource.clone())
        {
            return Err("flow rule value is invalid or duplicated".into());
        }
        output.push(CanonicalFlowRule {
            resource: input.resource,
            threshold,
        });
    }
    output.sort_by(|left, right| left.resource.cmp(&right.resource));
    Ok(output)
}

pub fn apply_flow_rules(rules: &[CanonicalFlowRule]) -> Result<(), String> {
    let sdk_rules = rules
        .iter()
        .map(|rule| {
            Ok(Arc::new(Rule {
                resource: rule.resource.clone(),
                threshold: rule.threshold.parse().map_err(|_| "invalid threshold")?,
                calculate_strategy: CalculateStrategy::Direct,
                control_strategy: ControlStrategy::Reject,
                ..Rule::default()
            }))
        })
        .collect::<Result<Vec<_>, &str>>()?;
    flow::load_rules(sdk_rules);
    Ok(())
}

pub fn canonical_digest(rules: &[CanonicalFlowRule]) -> String {
    let mut fingerprints = rules.iter().map(member_fingerprint).collect::<Vec<_>>();
    fingerprints.sort();
    let canonical = format!(
        "sentinel-flow-snapshot-v1\n{}{}",
        fingerprints.join("\n"),
        if fingerprints.is_empty() { "" } else { "\n" }
    );
    sha256_hex(canonical.as_bytes())
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn canonical_threshold(raw: &str) -> Result<String, String> {
    if raw.contains(['e', 'E'])
        || raw.starts_with('-')
        || raw.starts_with('+')
        || raw.starts_with('.')
        || raw.ends_with('.')
    {
        return Err("flow threshold is not a supported decimal".into());
    }
    let (whole, fraction) = raw.split_once('.').unwrap_or((raw, ""));
    if whole.is_empty()
        || (whole.len() > 1 && whole.starts_with('0'))
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || !fraction.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err("flow threshold is not a supported decimal".into());
    }
    let canonical_fraction = fraction.trim_end_matches('0');
    if canonical_fraction.len() > 6 {
        return Err("flow threshold precision exceeds six decimal places".into());
    }
    let normalized = if canonical_fraction.is_empty() {
        whole.to_string()
    } else {
        format!("{whole}.{canonical_fraction}")
    };
    let numeric = normalized
        .parse::<f64>()
        .map_err(|_| "flow threshold is invalid")?;
    if !numeric.is_finite() || numeric <= 0.0 || numeric > MAX_THRESHOLD {
        return Err("flow threshold is outside supported bounds".into());
    }
    Ok(normalized)
}

fn member_fingerprint(rule: &CanonicalFlowRule) -> String {
    let canonical = format!(
        "sentinel-flow-member-v1\n{}:{}\n{}:{}\n",
        rule.resource.len(),
        rule.resource,
        rule.threshold.len(),
        rule.threshold
    );
    sha256_hex(canonical.as_bytes())
}

pub fn member_fingerprints(rules: &[CanonicalFlowRule]) -> Vec<String> {
    let mut fingerprints = rules.iter().map(member_fingerprint).collect::<Vec<_>>();
    fingerprints.sort();
    fingerprints
}

#[cfg(test)]
mod tests {
    use super::*;
    use sentinel_core::{base::TrafficType, EntryBuilder};

    #[test]
    fn java_and_go_flow_subsets_normalize_to_the_same_snapshot() {
        let java = r#"[{"resource":"orders","grade":1,"count":2,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#;
        let go = r#"[{"resource":"orders","threshold":2,"statIntervalInMs":1000,"tokenCalculateStrategy":0,"controlBehavior":0,"relationStrategy":0}]"#;
        let java_rules = decode_flow_rules(java).unwrap();
        let go_rules = decode_flow_rules(go).unwrap();
        assert_eq!(java_rules, go_rules);
        assert_eq!(canonical_digest(&java_rules), canonical_digest(&go_rules));
        assert_eq!(
            member_fingerprints(&java_rules),
            ["9eaf17be84259e061c56ca451a91ffa16e4bda1de2f8ae01976088d13ab2e611"]
        );
        assert_eq!(
            canonical_digest(&decode_flow_rules("[]").unwrap()),
            "942fbd9bddd67e07292588bb949d003dd71e6cd73c6ae70333ab11d8ab7b2ff0"
        );
        assert_eq!(canonical_digest(&java_rules), canonical_digest(&decode_flow_rules(
            r#"[{"resource":"orders","grade":1,"count":2.000000,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#
        ).unwrap()));
    }

    #[test]
    fn invalid_or_unmodeled_candidates_are_rejected_as_a_whole() {
        for body in [
            r#"[{"resource":"orders","grade":0,"count":2}]"#,
            r#"[{"resource":"orders","grade":1,"count":2,"unknown":true}]"#,
            r#"[{"resource":"orders","grade":1,"count":2},{"resource":"orders","grade":1,"count":3}]"#,
            r#"[{"resource":"orders","grade":1,"count":2,"clusterMode":true}]"#,
            r#"[{"resource":"orders","grade":1,"count":2.1234567}]"#,
            r#"[{"resource":"orders","grade":1,"count":1e2}]"#,
        ] {
            assert!(decode_flow_rules(body).is_err(), "accepted {body}");
        }
    }

    #[test]
    fn managed_envelope_checks_identity_checksum_sequence_fields_and_payload() {
        let payload = r#"[{"resource":"orders","grade":1,"count":2}]"#;
        let digest = sha256_hex(payload.as_bytes());
        let valid = format!(
            r#"{{"protocol_version":"{MANAGED_PROTOCOL}","binding_id":"binding-01","publication_id":"publication-42","target_version_id":"version-42","publication_sequence":42,"rule_kind":"flow","profile_id":"sentinel-rust-v1","payload_sha256":"{digest}","rule_payload":{}}}"#,
            serde_json::to_string(payload).unwrap()
        );
        let (rules, publication) =
            decode_managed_flow_envelope(&valid, "binding-01", "sentinel-rust-v1").unwrap();
        assert_eq!(rules.len(), 1);
        assert_eq!(
            publication.tuple(),
            ("binding-01", "publication-42", "version-42")
        );
        assert_eq!(publication.sequence(), 42);
        assert_eq!(publication.payload_sha256(), digest);
        for invalid in [
            valid.replace("binding-01", "binding-other"),
            valid.replace(&digest, &"0".repeat(64)),
            valid.replace("\"publication_sequence\":42", "\"publication_sequence\":0"),
            valid.replace("\"rule_kind\":\"flow\"", "\"rule_kind\":\"degrade\""),
            valid.replace(
                "\"profile_id\":\"sentinel-rust-v1\"",
                "\"profile_id\":\"unknown\"",
            ),
            valid.replace(
                "\"profile_id\":\"sentinel-rust-v1\"",
                "\"profile_id\":\"sentinel-rust-v1\",\"unknown\":true",
            ),
        ] {
            assert!(
                decode_managed_flow_envelope(&invalid, "binding-01", "sentinel-rust-v1").is_err()
            );
        }
    }

    #[test]
    fn official_engine_applies_qps_flow_and_rejects_over_limit_entry() {
        sentinel_core::init_default().unwrap();
        let resource = format!("rust-runtime-contract-{}", std::process::id());
        let candidate = decode_flow_rules(&format!(
            r#"[{{"resource":"{resource}","grade":1,"count":1,"strategy":0,"controlBehavior":0,"limitApp":"default"}}]"#
        ))
        .unwrap();
        apply_flow_rules(&candidate).unwrap();

        let first = EntryBuilder::new(resource.clone())
            .with_traffic_type(TrafficType::Inbound)
            .build();
        assert!(first.is_ok(), "first request should pass the QPS limit");
        first.unwrap().exit();

        let second = EntryBuilder::new(resource)
            .with_traffic_type(TrafficType::Inbound)
            .build();
        assert!(
            second.is_err(),
            "second request in the same second must be rejected"
        );
    }
}
