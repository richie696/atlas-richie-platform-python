package main

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/nacos-group/nacos-sdk-go/v2/clients"
	"github.com/nacos-group/nacos-sdk-go/v2/common/constant"
	"github.com/nacos-group/nacos-sdk-go/v2/vo"
)

const maxRuleSnapshotBytes = 65_536

type ruleSnapshotSource interface {
	Read() (string, error)
	Close() error
}

type ruleSourceFailureKind string

const (
	ruleSourceMissing     ruleSourceFailureKind = "missing"
	ruleSourceRejected    ruleSourceFailureKind = "rejected"
	ruleSourceUnavailable ruleSourceFailureKind = "unavailable"
)

type ruleSourceFailure struct{ kind ruleSourceFailureKind }

type nacosConfigClient interface {
	GetConfig(vo.ConfigParam) (string, error)
	CloseClient()
}

func (failure ruleSourceFailure) Error() string {
	return "rule source read failed: " + string(failure.kind)
}

type nacosRuleSnapshotSource struct {
	client nacosConfigClient
	config vo.ConfigParam
}

func (source *nacosRuleSnapshotSource) Read() (string, error) {
	content, err := source.client.GetConfig(source.config)
	if err != nil {
		return "", ruleSourceFailure{kind: ruleSourceUnavailable}
	}
	return content, nil
}

func (source *nacosRuleSnapshotSource) Close() error {
	source.client.CloseClient()
	return nil
}

type consulRuleSnapshotSource struct {
	client     *http.Client
	endpoint   *url.URL
	key        string
	datacenter string
	token      string
}

func newConsulRuleSnapshotSource(endpoint, key, datacenter, token string) (*consulRuleSnapshotSource, error) {
	parsed, err := url.Parse(strings.TrimSpace(endpoint))
	if err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" ||
		(parsed.Scheme != "http" && parsed.Scheme != "https") {
		return nil, fmt.Errorf("Consul endpoint must be an HTTP(S) URL without credentials or query")
	}
	if !validConsulRuleKey(key) {
		return nil, fmt.Errorf("Consul KV key is invalid")
	}
	return &consulRuleSnapshotSource{
		client: &http.Client{
			Timeout:       5 * time.Second,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
		},
		endpoint: parsed, key: key, datacenter: datacenter, token: token,
	}, nil
}

func (source *consulRuleSnapshotSource) Read() (string, error) {
	requestURL := *source.endpoint
	// Keep key separators as path separators and let url.URL escape each
	// character exactly once when String() builds the request URI.
	requestURL.Path = strings.TrimRight(requestURL.Path, "/") + "/v1/kv/" + source.key
	query := requestURL.Query()
	query.Set("raw", "true")
	if source.datacenter != "" {
		query.Set("dc", source.datacenter)
	}
	requestURL.RawQuery = query.Encode()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, requestURL.String(), nil)
	if err != nil {
		return "", ruleSourceFailure{kind: ruleSourceUnavailable}
	}
	request.Header.Set("Accept", "application/octet-stream")
	if source.token != "" {
		request.Header.Set("X-Consul-Token", source.token)
	}
	response, err := source.client.Do(request)
	if err != nil {
		return "", ruleSourceFailure{kind: ruleSourceUnavailable}
	}
	defer response.Body.Close()
	switch response.StatusCode {
	case http.StatusNotFound:
		return "", ruleSourceFailure{kind: ruleSourceMissing}
	case http.StatusUnauthorized, http.StatusForbidden:
		return "", ruleSourceFailure{kind: ruleSourceRejected}
	case http.StatusOK:
	default:
		return "", ruleSourceFailure{kind: ruleSourceUnavailable}
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxRuleSnapshotBytes+1))
	if err != nil || len(body) > maxRuleSnapshotBytes {
		return "", ruleSourceFailure{kind: ruleSourceUnavailable}
	}
	return string(body), nil
}

func (source *consulRuleSnapshotSource) Close() error { return nil }

func newRuleSnapshotSourceFromEnvironment() (ruleSnapshotSource, error) {
	provider := strings.TrimSpace(os.Getenv("RULE_SOURCE_PROVIDER"))
	if provider == "" {
		provider = "nacos"
	}
	switch provider {
	case "nacos":
		namespace := setting("NACOS_NAMESPACE", "public")
		clientConfig := &constant.ClientConfig{
			TimeoutMs: 5000, NamespaceId: namespace,
			NotLoadCacheAtStart: true, DisableUseSnapShot: true, LogLevel: "warn",
			CacheDir: setting("NACOS_CACHE_DIR", ".nacos-cache"), LogDir: setting("NACOS_LOG_DIR", ".nacos-log"),
		}
		if strings.ToLower(strings.TrimSpace(os.Getenv("NACOS_AUTH_ENABLED"))) != "false" {
			password := strings.TrimSpace(os.Getenv("NACOS_PASSWORD"))
			if password == "" {
				return nil, fmt.Errorf("NACOS_PASSWORD is required when Nacos authentication is enabled")
			}
			clientConfig.Username = setting("NACOS_USERNAME", "nacos")
			clientConfig.Password = password
		}
		client, err := clients.NewConfigClient(vo.NacosClientParam{
			ClientConfig: clientConfig,
			ServerConfigs: []constant.ServerConfig{{IpAddr: setting("NACOS_SERVER_ADDR", "127.0.0.1"),
				Port: uint64(numberSetting("NACOS_SERVER_PORT", 8848)), ContextPath: "/nacos"}},
		})
		if err != nil {
			return nil, fmt.Errorf("create Nacos rule source client")
		}
		return &nacosRuleSnapshotSource{client: client, config: vo.ConfigParam{
			DataId: setting("NACOS_DATA_ID", "sentinel-e2e-20261017-go-flow-rules.json"),
			Group:  setting("NACOS_GROUP", "DEFAULT_GROUP"),
		}}, nil
	case "consul":
		return newConsulRuleSnapshotSource(os.Getenv("CONSUL_URL"), os.Getenv("CONSUL_KEY"),
			strings.TrimSpace(os.Getenv("CONSUL_DATACENTER")), os.Getenv("CONSUL_TOKEN"))
	default:
		return nil, fmt.Errorf("unsupported RULE_SOURCE_PROVIDER")
	}
}

func validConsulRuleKey(key string) bool {
	if key == "" || len([]rune(key)) > 512 || strings.HasPrefix(key, "/") || strings.HasSuffix(key, "/") ||
		strings.ContainsAny(key, "\\?#") {
		return false
	}
	for _, segment := range strings.Split(key, "/") {
		if segment == "" || segment == "." || segment == ".." {
			return false
		}
	}
	return true
}
