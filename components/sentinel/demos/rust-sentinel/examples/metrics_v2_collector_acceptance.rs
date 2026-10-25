#![allow(dead_code)]

#[path = "../src/metrics_v2.rs"]
mod metrics_v2;
#[path = "../src/reporting.rs"]
mod reporting;
#[path = "../src/rules.rs"]
mod rules;
#[path = "../src/source.rs"]
mod source;

use metrics_v2::MetricsV2Reporter;
use std::{env, io, sync::Arc, time::Duration};
use uuid::Uuid;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let epoch = env::var("RUST_METRICS_TEST_EPOCH")?;
    Uuid::parse_str(&epoch).map_err(|_| io::Error::other("test epoch is invalid"))?;
    let reporter = Arc::new(
        MetricsV2Reporter::from_environment(&epoch)
            .map_err(io::Error::other)?
            .ok_or_else(|| io::Error::other("Metrics V2 reporter is not configured"))?,
    );
    reporter.record_http_response(true, true, false, true, Duration::from_millis(7));
    reporter.record_http_response(true, false, true, false, Duration::from_millis(13));
    reporter.start();

    if !reporter
        .wait_for_acknowledgement(1, Duration::from_secs(20))
        .await
    {
        return Err(io::Error::other("Collector durable receipt was not confirmed").into());
    }
    println!("Rust Metrics V2 durable receipt confirmed");
    Ok(())
}
