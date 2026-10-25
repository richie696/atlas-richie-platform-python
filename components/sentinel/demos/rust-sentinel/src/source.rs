use async_trait::async_trait;
use nacos_sdk::api::{
    config::{ConfigService, ConfigServiceBuilder},
    props::ClientProps,
};
use reqwest::{header::HeaderValue, Client, StatusCode};
use serde::Deserialize;
use std::{env, time::Duration};
use url::Url;

const MAX_CONSUL_RESPONSE_BYTES: usize = 128 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuleSnapshot {
    pub content: String,
    pub revision: String,
}

#[derive(Debug, PartialEq, Eq)]
pub enum SourceError {
    Missing,
    Rejected,
    Unavailable,
    Invalid,
}

impl std::fmt::Display for SourceError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let description = match self {
            Self::Missing => "rule snapshot is missing",
            Self::Rejected => "rule source rejected the request",
            Self::Unavailable => "rule source is unavailable",
            Self::Invalid => "rule source configuration or snapshot is invalid",
        };
        formatter.write_str(description)
    }
}

impl std::error::Error for SourceError {}

#[async_trait]
pub trait RuleSnapshotSource: Send + Sync {
    async fn read_snapshot(&self) -> Result<RuleSnapshot, SourceError>;
}

pub struct NacosRuleSnapshotSource {
    service: ConfigService,
    data_id: String,
    group: String,
}

impl NacosRuleSnapshotSource {
    pub async fn from_environment() -> Result<Self, SourceError> {
        let address = required_env("NACOS_SERVER_ADDR")?;
        let namespace = env::var("NACOS_NAMESPACE").unwrap_or_default();
        let data_id = required_env("NACOS_DATA_ID")?;
        let group = env::var("NACOS_GROUP").unwrap_or_else(|_| "DEFAULT_GROUP".into());
        let mut props = ClientProps::new()
            .server_addr(address)
            .namespace(namespace)
            .app_name("sentinel-rust-runtime-demo");
        if let (Ok(username), Ok(password)) =
            (env::var("NACOS_USERNAME"), env::var("NACOS_PASSWORD"))
        {
            props = props.auth_username(username).auth_password(password);
        }
        let service = ConfigServiceBuilder::new(props)
            .enable_auth_plugin_http()
            .build()
            .await
            .map_err(|_| SourceError::Unavailable)?;
        Ok(Self {
            service,
            data_id,
            group,
        })
    }
}

#[async_trait]
impl RuleSnapshotSource for NacosRuleSnapshotSource {
    async fn read_snapshot(&self) -> Result<RuleSnapshot, SourceError> {
        let response = self
            .service
            .get_config(self.data_id.clone(), self.group.clone())
            .await
            .map_err(classify_nacos_error)?;
        let content = response.content().to_owned();
        let revision = response.md5().to_owned();
        if content.len() > 65_536 {
            return Err(SourceError::Invalid);
        }
        if content.trim().is_empty() {
            return Err(SourceError::Invalid);
        }
        Ok(RuleSnapshot { content, revision })
    }
}

fn classify_nacos_error(error: nacos_sdk::api::error::Error) -> SourceError {
    use nacos_sdk::api::error::Error;
    match error {
        Error::ConfigNotFound(_) => SourceError::Missing,
        // The SDK returns server error codes for rejected requests. Do not
        // inspect/log server messages: they may include deployment metadata.
        Error::ErrResponse(_, _, 401 | 403, _) => SourceError::Rejected,
        Error::InvalidParam(_, _) => SourceError::Invalid,
        _ => SourceError::Unavailable,
    }
}

pub struct ConsulRuleSnapshotSource {
    client: Client,
    endpoint: Url,
    key: String,
    datacenter: Option<String>,
    token: Option<HeaderValue>,
}

impl ConsulRuleSnapshotSource {
    pub fn from_environment() -> Result<Self, SourceError> {
        let endpoint =
            Url::parse(&required_env("CONSUL_URL")?).map_err(|_| SourceError::Invalid)?;
        if !matches!(endpoint.scheme(), "http" | "https")
            || endpoint.host_str().is_none()
            || endpoint.query().is_some()
            || endpoint.fragment().is_some()
        {
            return Err(SourceError::Invalid);
        }
        let token = env::var("CONSUL_TOKEN")
            .ok()
            .map(|value| HeaderValue::from_str(&value).map_err(|_| SourceError::Invalid))
            .transpose()?;
        let client = Client::builder()
            .timeout(Duration::from_secs(3))
            .build()
            .map_err(|_| SourceError::Unavailable)?;
        Ok(Self {
            client,
            endpoint,
            key: required_env("CONSUL_KEY")?,
            datacenter: env::var("CONSUL_DATACENTER").ok(),
            token,
        })
    }
}

#[derive(Deserialize)]
struct ConsulKvValue {
    #[serde(rename = "ModifyIndex")]
    modify_index: u64,
    #[serde(rename = "Value")]
    value: Option<String>,
}

#[async_trait]
impl RuleSnapshotSource for ConsulRuleSnapshotSource {
    async fn read_snapshot(&self) -> Result<RuleSnapshot, SourceError> {
        let mut endpoint = self.endpoint.clone();
        let base = endpoint.path().trim_end_matches('/');
        let encoded_key = self
            .key
            .split('/')
            .map(|part| {
                // form encoding emits `+` for spaces, but Consul interprets
                // `+` literally in a KV path segment. Use RFC 3986 `%20`.
                url::form_urlencoded::byte_serialize(part.as_bytes())
                    .collect::<String>()
                    .replace('+', "%20")
            })
            .collect::<Vec<_>>()
            .join("/");
        endpoint.set_path(&format!("{base}/v1/kv/{encoded_key}"));
        if let Some(datacenter) = &self.datacenter {
            endpoint.query_pairs_mut().append_pair("dc", datacenter);
        }
        let mut request = self.client.get(endpoint);
        if let Some(token) = &self.token {
            request = request.header("X-Consul-Token", token.clone());
        }
        let response = request.send().await.map_err(|_| SourceError::Unavailable)?;
        if response.status() == StatusCode::NOT_FOUND {
            return Err(SourceError::Missing);
        }
        if matches!(
            response.status(),
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
        ) {
            return Err(SourceError::Rejected);
        }
        if !response.status().is_success() {
            return Err(SourceError::Unavailable);
        }
        if response
            .content_length()
            .is_some_and(|length| length > MAX_CONSUL_RESPONSE_BYTES as u64)
        {
            return Err(SourceError::Invalid);
        }
        let body = response
            .bytes()
            .await
            .map_err(|_| SourceError::Unavailable)?;
        if body.len() > MAX_CONSUL_RESPONSE_BYTES {
            return Err(SourceError::Invalid);
        }
        let mut values: Vec<ConsulKvValue> =
            serde_json::from_slice(&body).map_err(|_| SourceError::Invalid)?;
        if values.len() != 1 {
            return Err(SourceError::Invalid);
        }
        let value = values.pop().ok_or(SourceError::Invalid)?;
        let bytes = value.value.ok_or(SourceError::Invalid)?;
        use base64::Engine;
        let content = base64::engine::general_purpose::STANDARD
            .decode(bytes)
            .map_err(|_| SourceError::Invalid)?;
        if content.is_empty() || content.len() > 65_536 {
            return Err(SourceError::Invalid);
        }
        let content = String::from_utf8(content).map_err(|_| SourceError::Invalid)?;
        Ok(RuleSnapshot {
            content,
            revision: value.modify_index.to_string(),
        })
    }
}

pub async fn selected_source() -> Result<Box<dyn RuleSnapshotSource>, SourceError> {
    match env::var("RULE_SOURCE_PROVIDER")
        .as_deref()
        .unwrap_or("nacos")
    {
        "nacos" => Ok(Box::new(NacosRuleSnapshotSource::from_environment().await?)),
        "consul" => Ok(Box::new(ConsulRuleSnapshotSource::from_environment()?)),
        _ => Err(SourceError::Invalid),
    }
}

fn required_env(name: &str) -> Result<String, SourceError> {
    env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .ok_or(SourceError::Invalid)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nacos_errors_are_classified_by_typed_sdk_code_not_error_text() {
        use nacos_sdk::api::error::Error;

        assert_eq!(
            classify_nacos_error(Error::ConfigNotFound("secret-looking message".into())),
            SourceError::Missing
        );
        assert_eq!(
            classify_nacos_error(Error::ErrResponse(
                None,
                0,
                401,
                Some("private detail".into())
            )),
            SourceError::Rejected
        );
        assert_eq!(
            classify_nacos_error(Error::ErrResponse(
                None,
                0,
                500,
                Some("private detail".into())
            )),
            SourceError::Unavailable
        );
    }

    #[tokio::test]
    async fn consul_adapter_reads_exact_key_and_decodes_provider_value() {
        use tokio::{
            io::{AsyncReadExt, AsyncWriteExt},
            net::TcpListener,
        };

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut request = vec![0; 4096];
            let count = socket.read(&mut request).await.unwrap();
            let request = String::from_utf8_lossy(&request[..count]);
            assert!(
                request.starts_with("GET /v1/kv/rules/flow%20rules?dc=dc-a HTTP/1.1"),
                "unexpected request target: {request}"
            );
            assert!(request
                .to_ascii_lowercase()
                .contains("x-consul-token: test-token"));
            let body = r#"[{"ModifyIndex":42,"Value":"W10="}]"#;
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(), body
            );
            socket.write_all(response.as_bytes()).await.unwrap();
        });

        let source = ConsulRuleSnapshotSource {
            client: Client::new(),
            endpoint: Url::parse(&format!("http://{address}")).unwrap(),
            key: "rules/flow rules".into(),
            datacenter: Some("dc-a".into()),
            token: Some(HeaderValue::from_static("test-token")),
        };
        let snapshot = source.read_snapshot().await.unwrap();
        assert_eq!(snapshot.revision, "42");
        assert_eq!(snapshot.content, "[]");
        server.await.unwrap();
    }
}
