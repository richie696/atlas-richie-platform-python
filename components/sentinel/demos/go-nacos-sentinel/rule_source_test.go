package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/nacos-group/nacos-sdk-go/v2/vo"
)

func TestConsulRuleSnapshotSourceReadsExactKVWithDatacenterAndToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			t.Errorf("method = %s, want GET", request.Method)
		}
		if got := request.URL.EscapedPath(); got != "/gateway/v1/kv/sentinel/rules%20v1.json" {
			t.Errorf("escaped path = %q", got)
		}
		if request.URL.Query().Get("raw") != "true" || request.URL.Query().Get("dc") != "dc-east" {
			t.Errorf("query = %v", request.URL.Query())
		}
		if request.Header.Get("X-Consul-Token") != "fixture-secret" {
			t.Errorf("Consul token header missing")
		}
		writer.WriteHeader(http.StatusOK)
		_, _ = writer.Write([]byte("[]"))
	}))
	defer server.Close()

	source, err := newConsulRuleSnapshotSource(server.URL+"/gateway", "sentinel/rules v1.json", "dc-east", "fixture-secret")
	if err != nil {
		t.Fatal(err)
	}
	content, err := source.Read()
	if err != nil || content != "[]" {
		t.Fatalf("Read() = %q, %v", content, err)
	}
	if err := source.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestConsulRuleSnapshotSourceClassifiesFailuresWithoutLeakingBodyOrToken(t *testing.T) {
	for _, testCase := range []struct {
		name   string
		status int
		kind   ruleSourceFailureKind
	}{
		{name: "missing", status: http.StatusNotFound, kind: ruleSourceMissing},
		{name: "unauthorized", status: http.StatusUnauthorized, kind: ruleSourceRejected},
		{name: "forbidden", status: http.StatusForbidden, kind: ruleSourceRejected},
		{name: "unavailable", status: http.StatusServiceUnavailable, kind: ruleSourceUnavailable},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
				writer.WriteHeader(testCase.status)
				_, _ = writer.Write([]byte("secret-body-must-not-escape"))
			}))
			defer server.Close()
			source, err := newConsulRuleSnapshotSource(server.URL, "rules/flow.json", "", "secret-token")
			if err != nil {
				t.Fatal(err)
			}
			_, err = source.Read()
			failure, ok := err.(ruleSourceFailure)
			if !ok || failure.kind != testCase.kind {
				t.Fatalf("Read() error = %#v, want kind %q", err, testCase.kind)
			}
			if strings.Contains(err.Error(), "secret") {
				t.Fatalf("failure leaked secret material: %q", err)
			}
		})
	}
}

func TestConsulRuleSnapshotSourceRejectsOversizedBody(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = writer.Write([]byte(strings.Repeat("x", maxRuleSnapshotBytes+1)))
	}))
	defer server.Close()
	source, err := newConsulRuleSnapshotSource(server.URL, "rules/flow.json", "", "")
	if err != nil {
		t.Fatal(err)
	}
	_, err = source.Read()
	failure, ok := err.(ruleSourceFailure)
	if !ok || failure.kind != ruleSourceUnavailable {
		t.Fatalf("Read() error = %#v, want unavailable", err)
	}
}

func TestConsulRuleSnapshotSourceValidatesEndpointAndKey(t *testing.T) {
	for _, testCase := range []struct {
		endpoint string
		key      string
	}{
		{endpoint: "ftp://consul.local", key: "rules/flow"},
		{endpoint: "http://user:pass@consul.local", key: "rules/flow"},
		{endpoint: "http://consul.local?token=secret", key: "rules/flow"},
		{endpoint: "http://consul.local", key: "../flow"},
		{endpoint: "http://consul.local", key: "rules//flow"},
	} {
		if _, err := newConsulRuleSnapshotSource(testCase.endpoint, testCase.key, "", ""); err == nil {
			t.Errorf("accepted endpoint=%q key=%q", testCase.endpoint, testCase.key)
		}
	}
}

type fakeNacosConfigClient struct {
	content  string
	readErr  error
	readCall int
	closed   bool
}

func (client *fakeNacosConfigClient) GetConfig(param vo.ConfigParam) (string, error) {
	client.readCall++
	if param.DataId != "flow.json" || param.Group != "DEFAULT_GROUP" {
		return "", fmt.Errorf("unexpected Nacos selector")
	}
	return client.content, client.readErr
}

func (client *fakeNacosConfigClient) CloseClient() { client.closed = true }

func TestNacosRuleSnapshotSourceAdaptsSDKAndClosesClient(t *testing.T) {
	client := &fakeNacosConfigClient{content: "[]"}
	source := &nacosRuleSnapshotSource{client: client, config: vo.ConfigParam{DataId: "flow.json", Group: "DEFAULT_GROUP"}}
	content, err := source.Read()
	if err != nil || content != "[]" || client.readCall != 1 {
		t.Fatalf("Read() = %q, %v, calls=%d", content, err, client.readCall)
	}
	if err := source.Close(); err != nil || !client.closed {
		t.Fatalf("Close() = %v, closed=%v", err, client.closed)
	}
}
