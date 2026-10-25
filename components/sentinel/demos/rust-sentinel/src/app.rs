use crate::{reporting, rules, source};
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::IntoResponse,
    routing::get,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use source::{RuleSnapshot, RuleSnapshotSource};
use std::{
    env,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{sync::RwLock, time::sleep};
use uuid::Uuid;

#[derive(Clone)]
struct AppState {
    active: Arc<RwLock<ActiveSnapshot>>,
    metrics: Option<Arc<crate::metrics_v2::MetricsV2Reporter>>,
}

#[derive(Clone)]
struct ActiveSnapshot {
    source_revision: String,
    source_bytes_sha256: String,
    canonical_rules_sha256: String,
    rules: Vec<rules::CanonicalFlowRule>,
    member_fingerprints: Vec<String>,
    managed_publication: Option<rules::ManagedPublication>,
    last_failure: Option<&'static str>,
}

#[derive(Serialize)]
struct RulesResponse {
    rules_loaded: bool,
    profile_id: &'static str,
    rule_count: usize,
    source_revision: String,
    source_bytes_sha256: String,
    canonical_rules_sha256: String,
    last_failure: Option<&'static str>,
    membership_complete: bool,
    member_fingerprints: Vec<String>,
    managed_publication: Option<ManagedPublicationResponse>,
}

#[derive(Serialize)]
struct ManagedPublicationResponse {
    binding_id: String,
    publication_id: String,
    target_version_id: String,
    publication_sequence: u64,
    target_payload_sha256: String,
}

#[derive(Serialize)]
struct DemoResponse {
    status: u16,
    message: &'static str,
    elapsed_delay_seconds: u64,
}

#[derive(Deserialize)]
struct DelayQuery {
    delay_seconds: Option<u64>,
}

pub async fn run() -> Result<(), Box<dyn std::error::Error>> {
    sentinel_core::init_default()?;

    let source = source::selected_source().await?;
    let initial = source.read_snapshot().await?;
    let initial_state = apply_snapshot(&initial, None).map_err(std::io::Error::other)?;
    let process_epoch = Uuid::new_v4().to_string();
    let metrics = crate::metrics_v2::MetricsV2Reporter::from_environment(&process_epoch)
        .map_err(std::io::Error::other)?
        .map(Arc::new);
    if let Some(reporter) = &metrics {
        reporter.start();
    }
    let reporter = reporting::RuleLoadReporter::from_environment(process_epoch)
        .map_err(std::io::Error::other)?
        .map(Arc::new);
    if let Some(reporter) = &reporter {
        reporter.applied(
            &initial,
            &reporting_facts(&initial_state),
            initial_state.managed_publication.as_ref(),
        );
        let heartbeat_reporter = reporter.clone();
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(30));
            interval.tick().await;
            loop {
                interval.tick().await;
                heartbeat_reporter.heartbeat();
            }
        });
    }
    let app_state = AppState {
        active: Arc::new(RwLock::new(initial_state)),
        metrics,
    };
    tokio::spawn(poll_source(
        Arc::from(source),
        app_state.active.clone(),
        reporter,
    ));

    let app = Router::new()
        .route("/health", get(health))
        .route("/rules", get(read_rules))
        .route("/api/hello", get(demo))
        .route("/demo", get(demo))
        .with_state(app_state);
    let address = env::var("HTTP_ADDR").unwrap_or_else(|_| "127.0.0.1:18094".into());
    let listener = tokio::net::TcpListener::bind(&address).await?;
    println!("sentinel-rust-runtime-demo listening on {address}");
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health() -> impl IntoResponse {
    (StatusCode::OK, "ready")
}

async fn read_rules(State(state): State<AppState>) -> Json<RulesResponse> {
    let active = state.active.read().await;
    Json(RulesResponse {
        rules_loaded: true,
        profile_id: "sentinel-rust-v1",
        rule_count: active.rules.len(),
        source_revision: active.source_revision.clone(),
        source_bytes_sha256: active.source_bytes_sha256.clone(),
        canonical_rules_sha256: active.canonical_rules_sha256.clone(),
        last_failure: active.last_failure,
        membership_complete: true,
        member_fingerprints: active.member_fingerprints.clone(),
        managed_publication: active.managed_publication.as_ref().map(|publication| {
            let (binding_id, _, _) = publication.tuple();
            ManagedPublicationResponse {
                binding_id: binding_id.into(),
                publication_id: publication.publication_id().into(),
                target_version_id: publication.target_version_id().into(),
                publication_sequence: publication.sequence(),
                target_payload_sha256: publication.payload_sha256().into(),
            }
        }),
    })
}

async fn demo(State(state): State<AppState>, Query(query): Query<DelayQuery>) -> impl IntoResponse {
    let delay_seconds = query.delay_seconds.unwrap_or(0).min(30);
    let started = Instant::now();
    // The SDK's synchronous Entry guard must cover the simulated business
    // delay, but cannot cross an async await. Isolate both in a blocking task.
    let response = match tokio::task::spawn_blocking(move || {
        let entry = sentinel_core::EntryBuilder::new("GET /api/hello".to_string())
            .with_traffic_type(sentinel_core::base::TrafficType::Inbound)
            .build();
        match entry {
            Ok(entry) => {
                std::thread::sleep(Duration::from_secs(delay_seconds));
                entry.exit();
                Ok(DemoResponse {
                    status: 200,
                    message: "allowed",
                    elapsed_delay_seconds: delay_seconds,
                })
            }
            Err(_) => Err(DemoResponse {
                status: 429,
                message: "blocked",
                elapsed_delay_seconds: 0,
            }),
        }
    })
    .await
    {
        Ok(Ok(response)) => (StatusCode::OK, Json(response)),
        Ok(Err(response)) => (StatusCode::TOO_MANY_REQUESTS, Json(response)),
        Err(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(DemoResponse {
                status: 500,
                message: "request_failed",
                elapsed_delay_seconds: 0,
            }),
        ),
    };
    if let Some(metrics) = &state.metrics {
        let status = match &response {
            (StatusCode::OK, _) => 200,
            (StatusCode::TOO_MANY_REQUESTS, _) => 429,
            _ => 500,
        };
        metrics.record_http_response(
            true,
            status == 200,
            status == 429,
            status == 200,
            started.elapsed(),
        );
    }
    response
}

async fn poll_source(
    source: Arc<dyn RuleSnapshotSource>,
    active: Arc<RwLock<ActiveSnapshot>>,
    reporter: Option<Arc<reporting::RuleLoadReporter>>,
) {
    let interval = env::var("POLL_INTERVAL_MS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value >= 100)
        .unwrap_or(1_000);
    loop {
        sleep(Duration::from_millis(interval)).await;
        match source.read_snapshot().await {
            Ok(candidate) => {
                let current_snapshot = active.read().await.clone();
                match apply_snapshot(&candidate, Some(&current_snapshot)) {
                    Ok(snapshot) => {
                        let mut current = active.write().await;
                        if current.source_bytes_sha256 != snapshot.source_bytes_sha256
                            || current.canonical_rules_sha256 != snapshot.canonical_rules_sha256
                            || current.source_revision != snapshot.source_revision
                        {
                            if let Some(reporter) = &reporter {
                                reporter.applied(
                                    &candidate,
                                    &reporting_facts(&snapshot),
                                    snapshot.managed_publication.as_ref(),
                                );
                            }
                            *current = snapshot;
                        } else {
                            current.last_failure = None;
                        }
                    }
                    Err(_) => {
                        active.write().await.last_failure = Some("validation_rejected");
                        if let Some(reporter) = &reporter {
                            reporter.failed("validation_rejected");
                        }
                    }
                }
            }
            Err(_) => {
                active.write().await.last_failure = Some("source_unavailable");
                if let Some(reporter) = &reporter {
                    reporter.failed("source_unavailable");
                }
            }
        }
    }
}

fn reporting_facts(active: &ActiveSnapshot) -> reporting::AppliedFacts {
    reporting::AppliedFacts {
        source_bytes_sha256: active.source_bytes_sha256.clone(),
        canonical_rules_sha256: active.canonical_rules_sha256.clone(),
        member_fingerprints: active.member_fingerprints.clone(),
    }
}

fn apply_snapshot(
    snapshot: &RuleSnapshot,
    current: Option<&ActiveSnapshot>,
) -> Result<ActiveSnapshot, String> {
    let source_profile =
        env::var("RULE_SOURCE_PROFILE").unwrap_or_else(|_| "native-array-v1".into());
    let (decoded, managed_publication) = match source_profile.as_str() {
        "native-array-v1" => (rules::decode_flow_rules(&snapshot.content)?, None),
        "managed-envelope-v1" => {
            let binding_id = env::var("RULE_BINDING_ID")
                .map_err(|_| "managed profile requires a registered binding")?;
            let profile_id =
                env::var("RULE_PROFILE_ID").unwrap_or_else(|_| "sentinel-rust-v1".into());
            let (candidate, publication) =
                rules::decode_managed_flow_envelope(&snapshot.content, &binding_id, &profile_id)?;
            if let Some(previous) = current.and_then(|state| state.managed_publication.as_ref()) {
                if publication.sequence() < previous.sequence()
                    || (publication.sequence() == previous.sequence() && publication != *previous)
                {
                    return Err("managed publication sequence is stale or conflicting".into());
                }
            }
            (candidate, Some(publication))
        }
        _ => return Err("unsupported source profile".into()),
    };
    let canonical_rules_sha256 = rules::canonical_digest(&decoded);
    let source_bytes_sha256 = rules::sha256_hex(snapshot.content.as_bytes());
    let member_fingerprints = rules::member_fingerprints(&decoded);
    let rules_changed =
        current.is_none_or(|previous| previous.canonical_rules_sha256 != canonical_rules_sha256);
    if rules_changed {
        rules::apply_flow_rules(&decoded)?;
    }
    Ok(ActiveSnapshot {
        source_revision: snapshot.revision.clone(),
        source_bytes_sha256,
        canonical_rules_sha256,
        rules: decoded,
        member_fingerprints,
        managed_publication,
        last_failure: None,
    })
}
