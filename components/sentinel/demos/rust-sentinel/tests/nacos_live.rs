use nacos_sdk::api::{
    config::{ConfigService, ConfigServiceBuilder},
    props::ClientProps,
};
use serde_json::Value;
use std::{
    env,
    process::{Child, Command, Stdio},
    time::Duration,
};
use tokio::{
    net::TcpListener,
    time::{sleep, timeout},
};
use url::Url;
use uuid::Uuid;

#[tokio::test]
async fn live_nacos_initial_load_update_invalid_lkg_and_qps_decision() {
    if env::var("SENTINEL_T005_LIVE_NACOS").as_deref() != Ok("true") {
        eprintln!("skipped live Nacos acceptance; set SENTINEL_T005_LIVE_NACOS=true explicitly");
        return;
    }
    let result = run_live_nacos_acceptance().await;
    assert!(result.is_ok(), "{}", result.err().unwrap_or_default());
}

#[tokio::test]
async fn live_consul_initial_load_update_invalid_lkg_and_qps_decision() {
    if env::var("SENTINEL_T005_LIVE_CONSUL").as_deref() != Ok("true") {
        eprintln!("skipped live Consul acceptance; set SENTINEL_T005_LIVE_CONSUL=true explicitly");
        return;
    }
    let result = run_live_consul_acceptance().await;
    assert!(result.is_ok(), "{}", result.err().unwrap_or_default());
}

async fn run_live_nacos_acceptance() -> Result<(), String> {
    let address = env::var("NACOS_SERVER_ADDR").map_err(|_| "NACOS_SERVER_ADDR is required")?;
    let namespace = env::var("NACOS_NAMESPACE").unwrap_or_default();
    let username = env::var("NACOS_USERNAME").unwrap_or_default();
    let password = env::var("NACOS_PASSWORD").unwrap_or_default();
    let data_id = format!("sentinel-t005-rust-{}-flow.json", Uuid::new_v4());
    let group = format!("SENTINEL_T005_{}", Uuid::new_v4().simple());
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|_| "cannot reserve the runtime demo port")?;
    let demo_port = listener
        .local_addr()
        .map_err(|_| "cannot read reserved demo port")?
        .port();
    drop(listener);
    let props = ClientProps::new()
        .server_addr(address.clone())
        .namespace(namespace.clone())
        .app_name("sentinel-rust-live-acceptance")
        .auth_username(username)
        .auth_password(password);
    let service = ConfigServiceBuilder::new(props)
        .enable_auth_plugin_http()
        .build()
        .await
        .map_err(|_| "Nacos SDK could not initialize")?;
    let initial =
        r#"[{"resource":"sentinel-rust-demo-resource","grade":1,"count":1,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#
            .to_string();
    let published = service
        .publish_config(
            data_id.clone(),
            group.clone(),
            initial.clone(),
            Some("json".into()),
        )
        .await;
    if !matches!(published, Ok(true)) {
        let _ = service.remove_config(data_id, group).await;
        return Err("Nacos SDK could not publish the unique temporary config".into());
    }

    let runtime_result =
        run_runtime_assertions(&address, &namespace, &data_id, &group, demo_port, &service).await;
    let removed = service.remove_config(data_id.clone(), group.clone()).await;
    if !matches!(removed, Ok(true)) {
        return Err("failed to remove this test's unique temporary Nacos config".into());
    }
    runtime_result
}

async fn run_live_consul_acceptance() -> Result<(), String> {
    let consul_url = env::var("CONSUL_URL").map_err(|_| "CONSUL_URL is required")?;
    let key = format!("sentinel/t005/{}", Uuid::new_v4());
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|_| "cannot reserve the runtime demo port")?;
    let port = listener
        .local_addr()
        .map_err(|_| "cannot read reserved demo port")?
        .port();
    drop(listener);
    let base = Url::parse(&consul_url).map_err(|_| "Consul URL is invalid")?;
    let key_url = base
        .join(&format!("/v1/kv/{key}"))
        .map_err(|_| "Consul KV URL is invalid")?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .map_err(|_| "test HTTP client could not initialize")?;
    let initial = r#"[{"resource":"sentinel-rust-demo-resource","grade":1,"count":1,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#;
    let write_result = client.put(key_url.clone()).body(initial).send().await;
    if !matches!(write_result, Ok(response) if response.status().is_success()) {
        let _ = client.delete(key_url.clone()).send().await;
        return Err("Consul rejected the unique temporary KV write".into());
    }
    let demo_base = Url::parse(&format!("http://127.0.0.1:{port}"))
        .map_err(|_| "runtime demo URL is invalid")?;
    let runtime_result = async {
        let mut child = Command::new(env!("CARGO_BIN_EXE_sentinel-rust-runtime-demo"))
            .env("RULE_SOURCE_PROVIDER", "consul")
            .env("RULE_SOURCE_PROFILE", "native-array-v1")
            .env("CONSUL_URL", consul_url.trim_end_matches('/'))
            .env("CONSUL_KEY", &key)
            .env("HTTP_ADDR", format!("127.0.0.1:{port}"))
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
            .spawn().map_err(|_| "Rust Sentinel runtime could not start")?;
        let assertions = async {
            wait_ready(&client, demo_base.clone()).await?;
            let initial_state: Value = client.get(demo_base.join("/rules").unwrap()).send().await
                .map_err(|_| "initial Consul rule read failed")?.json().await
                .map_err(|_| "initial Consul rule response was invalid")?;
            let original_revision = initial_state["source_revision"].as_str().unwrap_or_default().to_owned();
            if initial_state["rule_count"] != 1 || original_revision.is_empty() {
                return Err("runtime did not load the Consul snapshot before business traffic".into());
            }
            if (demo_status(&client, demo_base.clone()).await?, demo_status(&client, demo_base.clone()).await?) != (200, 429) {
                return Err("Consul-loaded Flow rule did not reject over-limit traffic".into());
            }
            let invalid = r#"[{"resource":"sentinel-rust-demo-resource","grade":0,"count":3}]"#;
            let response = client.put(key_url.clone()).body(invalid).send().await
                .map_err(|_| "Consul invalid candidate write failed")?;
            if !response.status().is_success() { return Err("Consul rejected invalid-candidate test write".into()); }
            wait_for_failure(&client, demo_base.clone()).await?;
            let retained: Value = client.get(demo_base.join("/rules").unwrap()).send().await
                .map_err(|_| "LKG rule read failed")?.json().await
                .map_err(|_| "LKG rule response was invalid")?;
            if retained["source_revision"].as_str() != Some(&original_revision)
                || retained["canonical_rules_sha256"] != initial_state["canonical_rules_sha256"] {
                return Err("invalid Consul candidate replaced last-known-good rules".into());
            }
            let valid = r#"[{"resource":"sentinel-rust-demo-resource","grade":1,"count":2,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#;
            let response = client.put(key_url.clone()).body(valid).send().await
                .map_err(|_| "Consul valid candidate write failed")?;
            if !response.status().is_success() { return Err("Consul rejected valid update".into()); }
            let updated_state = wait_for_new_revision(&client, demo_base.clone(), &original_revision).await?;
            if updated_state["rule_count"] != 1 || updated_state["last_failure"] != Value::Null {
                return Err("valid Consul update did not clear the failure state".into());
            }
            assert_qps_limit(&client, demo_base.clone(), 2).await?;

            let before_outage: Value = client.get(demo_base.join("/rules").unwrap()).send().await
                .map_err(|_| "Consul rule read before outage failed")?.json().await
                .map_err(|_| "Consul rule response before outage was invalid")?;
            let removed = client.delete(key_url.clone()).send().await
                .map_err(|_| "Consul unique key delete for outage simulation failed")?;
            if !removed.status().is_success() {
                return Err("Consul rejected deletion of the unique outage-test key".into());
            }
            wait_for_failure_reason(&client, demo_base.clone(), "source_unavailable").await?;
            let during_outage: Value = client.get(demo_base.join("/rules").unwrap()).send().await
                .map_err(|_| "Consul rule read during outage failed")?.json().await
                .map_err(|_| "Consul rule response during outage was invalid")?;
            if during_outage["canonical_rules_sha256"] != before_outage["canonical_rules_sha256"] {
                return Err("Consul outage replaced the active last-known-good snapshot".into());
            }
            assert_qps_limit(&client, demo_base.clone(), 2).await?;

            let recovered = r#"[{"resource":"sentinel-rust-demo-resource","grade":1,"count":3,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#;
            let recovered_write = client.put(key_url.clone()).body(recovered).send().await
                .map_err(|_| "Consul recovery snapshot write failed")?;
            if !recovered_write.status().is_success() {
                return Err("Consul rejected the recovery snapshot".into());
            }
            let recovered_state = wait_for_new_revision(&client, demo_base.clone(),
                during_outage["source_revision"].as_str().unwrap_or_default()).await?;
            if recovered_state["last_failure"] != Value::Null {
                return Err("Consul source recovery did not clear its failure state".into());
            }
            assert_qps_limit(&client, demo_base.clone(), 3).await?;

            stop_child(&mut child);
            child = Command::new(env!("CARGO_BIN_EXE_sentinel-rust-runtime-demo"))
                .env("RULE_SOURCE_PROVIDER", "consul")
                .env("RULE_SOURCE_PROFILE", "native-array-v1")
                .env("CONSUL_URL", consul_url.trim_end_matches('/'))
                .env("CONSUL_KEY", &key)
                .env("HTTP_ADDR", format!("127.0.0.1:{port}"))
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .map_err(|_| "Rust Sentinel runtime could not restart")?;
            wait_ready(&client, demo_base.clone()).await?;
            let after_restart: Value = client.get(demo_base.join("/rules").unwrap()).send().await
                .map_err(|_| "Consul rule read after runtime restart failed")?.json().await
                .map_err(|_| "Consul rule response after runtime restart was invalid")?;
            if after_restart["source_revision"] != recovered_state["source_revision"]
                || after_restart["canonical_rules_sha256"] != recovered_state["canonical_rules_sha256"]
                || after_restart["last_failure"] != Value::Null
            {
                return Err("runtime restart did not load the recovered Consul snapshot first".into());
            }
            assert_qps_limit(&client, demo_base, 3).await?;
            Ok(())
        }.await;
        stop_child(&mut child);
        assertions
    }.await;
    let removed = client.delete(key_url).send().await;
    if !matches!(removed, Ok(response) if response.status().is_success()) {
        return Err("failed to remove this test's unique Consul KV key".into());
    }
    runtime_result
}

async fn run_runtime_assertions(
    address: &str,
    namespace: &str,
    data_id: &str,
    group: &str,
    port: u16,
    service: &ConfigService,
) -> Result<(), String> {
    let base = Url::parse(&format!("http://127.0.0.1:{port}"))
        .map_err(|_| "runtime demo URL is invalid")?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .map_err(|_| "test HTTP client could not initialize")?;
    let mut child = spawn_runtime(address, namespace, data_id, group, port)?;
    let result = async {
        wait_ready(&client, base.clone()).await?;
        let initial: Value = client
            .get(base.join("/rules").unwrap())
            .send().await.map_err(|_| "initial rule read failed")?
            .json().await.map_err(|_| "initial rule response was invalid")?;
        let original_revision = initial["source_revision"].as_str().unwrap_or_default().to_owned();
        if initial["rule_count"] != 1 || original_revision.is_empty() || initial["last_failure"] != Value::Null {
            return Err("runtime did not load the initial rule before business traffic".into());
        }
        let first = demo_status(&client, base.clone()).await?;
        let second = demo_status(&client, base.clone()).await?;
        if (first, second) != (200, 429) {
            return Err(format!("expected first request allowed and second blocked; got {first}/{second}"));
        }

        service.publish_config(
            data_id.into(), group.into(),
            r#"[{"resource":"sentinel-rust-demo-resource","grade":0,"count":3}]"#.into(),
            Some("json".into()),
        ).await.map_err(|_| "could not publish invalid candidate")?;
        wait_for_failure(&client, base.clone()).await?;
        let after_invalid: Value = client.get(base.join("/rules").unwrap()).send().await
            .map_err(|_| "rule read after invalid candidate failed")?.json().await
            .map_err(|_| "rule response after invalid candidate was invalid")?;
        if after_invalid["source_revision"].as_str() != Some(&original_revision)
            || after_invalid["canonical_rules_sha256"] != initial["canonical_rules_sha256"]
        {
            return Err("invalid update replaced the active last-known-good snapshot".into());
        }

        let updated = r#"[{"resource":"sentinel-rust-demo-resource","grade":1,"count":2,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#;
        service.publish_config(data_id.into(), group.into(), updated.into(), Some("json".into()))
            .await.map_err(|_| "could not publish valid update")?;
        let updated_state = wait_for_new_revision(&client, base.clone(), &original_revision).await?;
        if updated_state["rule_count"] != 1 || updated_state["last_failure"] != Value::Null {
            return Err("valid update did not replace the rejected candidate state".into());
        }
        assert_qps_limit(&client, base.clone(), 2).await?;

        if !matches!(service.remove_config(data_id.into(), group.into()).await, Ok(true)) {
            return Err("could not remove the unique Nacos config for outage simulation".into());
        }
        wait_for_failure_reason(&client, base.clone(), "source_unavailable").await?;
        let during_outage: Value = client.get(base.join("/rules").unwrap()).send().await
            .map_err(|_| "rule read during Nacos outage failed")?.json().await
            .map_err(|_| "rule response during Nacos outage was invalid")?;
        if during_outage["canonical_rules_sha256"] != updated_state["canonical_rules_sha256"] {
            return Err("Nacos outage replaced the active last-known-good snapshot".into());
        }
        assert_qps_limit(&client, base.clone(), 2).await?;

        let recovered = r#"[{"resource":"sentinel-rust-demo-resource","grade":1,"count":3,"strategy":0,"controlBehavior":0,"limitApp":"default"}]"#;
        service.publish_config(data_id.into(), group.into(), recovered.into(), Some("json".into()))
            .await.map_err(|_| "could not republish the Nacos recovery snapshot")?;
        let recovered_state = wait_for_new_revision(&client, base.clone(),
            during_outage["source_revision"].as_str().unwrap_or_default()).await?;
        if recovered_state["last_failure"] != Value::Null {
            return Err("Nacos source recovery did not clear its failure state".into());
        }
        assert_qps_limit(&client, base.clone(), 3).await?;

        stop_child(&mut child);
        child = spawn_runtime(address, namespace, data_id, group, port)?;
        wait_ready(&client, base.clone()).await?;
        let after_restart: Value = client.get(base.join("/rules").unwrap()).send().await
            .map_err(|_| "rule read after Nacos runtime restart failed")?.json().await
            .map_err(|_| "rule response after Nacos runtime restart was invalid")?;
        if after_restart["source_revision"] != recovered_state["source_revision"]
            || after_restart["canonical_rules_sha256"] != recovered_state["canonical_rules_sha256"]
            || after_restart["last_failure"] != Value::Null
        {
            return Err("runtime restart did not load the recovered Nacos snapshot first".into());
        }
        assert_qps_limit(&client, base, 3).await?;
        Ok(())
    }.await;
    stop_child(&mut child);
    result
}

fn spawn_runtime(
    address: &str,
    namespace: &str,
    data_id: &str,
    group: &str,
    port: u16,
) -> Result<Child, String> {
    Command::new(env!("CARGO_BIN_EXE_sentinel-rust-runtime-demo"))
        .env("RULE_SOURCE_PROVIDER", "nacos")
        .env("RULE_SOURCE_PROFILE", "native-array-v1")
        .env("NACOS_SERVER_ADDR", address)
        .env("NACOS_NAMESPACE", namespace)
        .env("NACOS_DATA_ID", data_id)
        .env("NACOS_GROUP", group)
        .env("HTTP_ADDR", format!("127.0.0.1:{port}"))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "Rust Sentinel runtime could not start".to_owned())
}

async fn wait_ready(client: &reqwest::Client, base: Url) -> Result<(), String> {
    timeout(Duration::from_secs(30), async {
        loop {
            if client
                .get(base.join("/health").unwrap())
                .send()
                .await
                .is_ok()
            {
                return Ok(());
            }
            sleep(Duration::from_millis(250)).await;
        }
    })
    .await
    .map_err(|_| "runtime did not become ready from the Nacos snapshot")?
}

async fn wait_for_failure(client: &reqwest::Client, base: Url) -> Result<(), String> {
    wait_for_failure_reason(client, base, "validation_rejected")
        .await
        .map(|_| ())
}

async fn wait_for_failure_reason(
    client: &reqwest::Client,
    base: Url,
    reason: &'static str,
) -> Result<Value, String> {
    wait_for_state(client, base, |state| state["last_failure"] == reason).await
}

async fn wait_for_new_revision(
    client: &reqwest::Client,
    base: Url,
    previous: &str,
) -> Result<Value, String> {
    wait_for_state(client, base, |state| {
        state["source_revision"]
            .as_str()
            .is_some_and(|revision| revision != previous)
    })
    .await
}

async fn wait_for_state<F>(
    client: &reqwest::Client,
    base: Url,
    predicate: F,
) -> Result<Value, String>
where
    F: Fn(&Value) -> bool,
{
    timeout(Duration::from_secs(30), async {
        loop {
            if let Ok(response) = client.get(base.join("/rules").unwrap()).send().await {
                if let Ok(state) = response.json::<Value>().await {
                    if predicate(&state) {
                        return Ok(state);
                    }
                }
            }
            sleep(Duration::from_millis(200)).await;
        }
    })
    .await
    .map_err(|_| "runtime did not observe the expected Nacos state")?
}

async fn demo_status(client: &reqwest::Client, base: Url) -> Result<u16, String> {
    client
        .get(base.join("/demo").unwrap())
        .send()
        .await
        .map(|response| response.status().as_u16())
        .map_err(|_| "demo request failed".to_owned())
}

async fn assert_qps_limit(
    client: &reqwest::Client,
    base: Url,
    allowed_requests: usize,
) -> Result<(), String> {
    sleep(Duration::from_millis(1_100)).await;
    let mut statuses = Vec::with_capacity(allowed_requests + 1);
    for _ in 0..=allowed_requests {
        statuses.push(demo_status(client, base.clone()).await?);
    }
    let expected = vec![200; allowed_requests]
        .into_iter()
        .chain([429])
        .collect::<Vec<_>>();
    if statuses != expected {
        return Err(format!(
            "expected QPS limit {allowed_requests} to allow then reject; got {statuses:?}"
        ));
    }
    Ok(())
}

fn stop_child(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}
