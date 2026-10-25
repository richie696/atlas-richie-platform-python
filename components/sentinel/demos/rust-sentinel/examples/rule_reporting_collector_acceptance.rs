#![allow(dead_code)]

#[path = "../src/reporting.rs"]
mod reporting;
#[path = "../src/rules.rs"]
mod rules;
#[path = "../src/source.rs"]
mod source;

use reporting::{AppliedFacts, RuleLoadReporter};
use source::RuleSnapshot;
use std::{env, io, time::Duration};
use uuid::Uuid;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    sentinel_core::init_default()?;
    let epoch = env::var("RUST_REPORTING_TEST_EPOCH")?;
    Uuid::parse_str(&epoch).map_err(|_| io::Error::other("test epoch is invalid"))?;
    let binding_id = env::var("RULE_BINDING_ID")?;
    let profile_id = env::var("RULE_PROFILE_ID")?;
    let payload = r#"[{"resource":"sentinel-rust-managed-demo-resource","grade":1,"count":10,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#;
    let payload_sha256 = rules::sha256_hex(payload.as_bytes());
    let envelope = serde_json::json!({
        "protocol_version": "atlas-richie.sentinel.managed-rule-publication/v1",
        "binding_id": binding_id,
        "publication_id": env::var("RULE_PUBLICATION_ID")?,
        "target_version_id": env::var("RULE_TARGET_VERSION_ID")?,
        "publication_sequence": 1,
        "rule_kind": "flow",
        "profile_id": profile_id,
        "payload_sha256": payload_sha256,
        "rule_payload": payload,
    })
    .to_string();
    let (candidate, publication) = rules::decode_managed_flow_envelope(
        &envelope,
        &env::var("RULE_BINDING_ID")?,
        &env::var("RULE_PROFILE_ID")?,
    )
    .map_err(io::Error::other)?;
    rules::apply_flow_rules(&candidate).map_err(io::Error::other)?;

    let Some(reporter) =
        RuleLoadReporter::from_environment(epoch.clone()).map_err(io::Error::other)?
    else {
        return Err(io::Error::other("Rule Load reporter is not configured").into());
    };
    let source = RuleSnapshot {
        content: envelope.clone(),
        revision: "consul-index-acceptance-v1".into(),
    };
    reporter.applied(
        &source,
        &AppliedFacts {
            source_bytes_sha256: rules::sha256_hex(envelope.as_bytes()),
            canonical_rules_sha256: rules::canonical_digest(&candidate),
            member_fingerprints: rules::member_fingerprints(&candidate),
        },
        Some(&publication),
    );
    if !reporter
        .wait_for_durable_acknowledgements(1, 1, Duration::from_secs(20))
        .await
    {
        return Err(io::Error::other("Collector did not durably acknowledge Rust reports").into());
    }
    println!("Rust rule observation and managed receipt durable ACKs confirmed");
    Ok(())
}
