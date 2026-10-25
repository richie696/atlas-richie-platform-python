package main

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestRealConsulPollingRuntimeAcceptance(t *testing.T) {
	if os.Getenv("SENTINEL_T004_CONSUL_ACCEPTANCE") != "true" {
		t.Skip("set SENTINEL_T004_CONSUL_ACCEPTANCE=true to run against an isolated Consul provider")
	}
	consulURL := strings.TrimRight(os.Getenv("SENTINEL_T004_CONSUL_URL"), "/")
	if !strings.HasPrefix(consulURL, "http://127.0.0.1:") {
		t.Fatal("Consul acceptance requires the loopback-only disposable provider URL")
	}
	key := fmt.Sprintf("sentinel/t004/go-%d/flow-rules.json", time.Now().UnixNano())
	if exists, err := consulKVExists(consulURL, key); err != nil || exists {
		t.Fatalf("check unique Consul key before use: exists=%t err=%v", exists, err)
	}
	created := false
	defer func() {
		if created {
			if err := consulKVDelete(consulURL, key); err != nil {
				t.Errorf("delete only this acceptance key: %v", err)
			}
		}
	}()
	if err := consulKVPut(consulURL, key, goAcceptanceRules(1)); err != nil {
		t.Fatal(err)
	}
	created = true

	runtimeDirectory := t.TempDir()
	binary := filepath.Join(runtimeDirectory, "sentinel-go-consul-acceptance")
	build := exec.Command("go", "build", "-o", binary, ".")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build Go Runtime: %v\n%s", err, output)
	}
	port := unusedGoAcceptancePort(t)
	logPath := filepath.Join(runtimeDirectory, "runtime.log")
	logFile, err := os.Create(logPath)
	if err != nil {
		t.Fatal(err)
	}
	defer logFile.Close()
	child := startGoConsulAcceptanceRuntime(t, binary, runtimeDirectory, logFile, consulURL, key, port)
	defer stopGoConsulAcceptanceRuntime(child)
	origin := fmt.Sprintf("http://127.0.0.1:%d", port)
	awaitGoAcceptanceHealth(t, child, origin)
	initial := awaitGoAcceptanceSnapshot(t, child, origin, "")
	initialHash := goAcceptanceValue(t, initial, "source_bytes_sha256")
	if !containsInt(goAcceptanceBurst(t, origin, 8), http.StatusTooManyRequests) {
		t.Fatal("official Go Sentinel engine did not enforce the initial Consul rule")
	}
	if err := consulKVPut(consulURL, key, goAcceptanceRules(100)); err != nil {
		t.Fatal(err)
	}
	updated := awaitGoConsulSnapshot(t, child, origin, initialHash)
	updatedHash := goAcceptanceValue(t, updated, "source_bytes_sha256")
	if statuses := goAcceptanceBurst(t, origin, 8); !allStatuses(statuses, http.StatusOK) {
		t.Fatalf("valid Consul update was not executed: %v", statuses)
	}
	if err := consulKVPut(consulURL, key, goAcceptanceInvalidRules()); err != nil {
		t.Fatal(err)
	}
	awaitGoAcceptanceLog(t, logPath, "polled rule update rejected: invalid_rules")
	if got := goAcceptanceReadRules(t, origin); goAcceptanceValue(t, got, "source_bytes_sha256") != updatedHash {
		t.Fatal("invalid Consul candidate replaced last-known-good rules")
	}
	if err := consulKVDelete(consulURL, key); err != nil {
		t.Fatal(err)
	}
	awaitGoAcceptanceLogWithin(t, logPath, "rule source unavailable; retaining last-known-good rules", 10*time.Second)
	if got := goAcceptanceReadRules(t, origin); goAcceptanceValue(t, got, "source_bytes_sha256") != updatedHash {
		t.Fatal("missing Consul key replaced the active snapshot")
	}
	if err := consulKVPut(consulURL, key, goAcceptanceRules(2)); err != nil {
		t.Fatal(err)
	}
	recovered := awaitGoConsulSnapshot(t, child, origin, updatedHash)
	recoveredHash := goAcceptanceValue(t, recovered, "source_bytes_sha256")
	if !containsInt(goAcceptanceBurst(t, origin, 8), http.StatusTooManyRequests) {
		t.Fatal("recovered restrictive Consul rule was not enforced")
	}
	stopGoConsulAcceptanceRuntime(child)
	child = startGoConsulAcceptanceRuntime(t, binary, runtimeDirectory, logFile, consulURL, key, unusedGoAcceptancePort(t))
	restartedOrigin := goConsulOrigin(child)
	awaitGoAcceptanceHealth(t, child, restartedOrigin)
	restarted := awaitGoAcceptanceSnapshot(t, child, restartedOrigin, "")
	if goAcceptanceValue(t, restarted, "source_bytes_sha256") != recoveredHash {
		t.Fatal("restarted Runtime did not load the exact persisted Consul snapshot before business traffic")
	}
	if !containsInt(goAcceptanceBurst(t, restartedOrigin, 8), http.StatusTooManyRequests) {
		t.Fatal("restarted Runtime did not execute the persisted restrictive rule")
	}
}

func startGoConsulAcceptanceRuntime(t *testing.T, binary, directory string, logFile *os.File, consulURL, key string, port int) *exec.Cmd {
	t.Helper()
	env := goAcceptanceEnvironment(os.Environ(), map[string]string{
		"RULE_SOURCE_PROVIDER": "consul", "CONSUL_URL": consulURL, "CONSUL_KEY": key,
		"CONSUL_DATACENTER": "", "CONSUL_TOKEN": "", "RULE_SOURCE_PROFILE": "native-array-v1",
		"DEMO_BIND_HOST": "127.0.0.1", "DEMO_PORT": fmt.Sprint(port),
		"NACOS_PASSWORD": "", "NACOS_AUTH_ENABLED": "false", "RULE_BINDING_ID": "",
		"METRICS_COLLECTOR_URL": "", "METRICS_REPORTER_ID": "",
	})
	child := exec.Command(binary)
	child.Dir, child.Env = directory, env
	child.Stdout, child.Stderr = logFile, logFile
	if err := child.Start(); err != nil {
		t.Fatalf("start Go Runtime with Consul source: %v", err)
	}
	return child
}

func stopGoConsulAcceptanceRuntime(child *exec.Cmd) {
	if child != nil && child.Process != nil {
		_ = child.Process.Kill()
		_, _ = child.Process.Wait()
	}
}

func goConsulOrigin(child *exec.Cmd) string {
	for _, entry := range child.Env {
		if strings.HasPrefix(entry, "DEMO_PORT=") {
			return "http://127.0.0.1:" + strings.TrimPrefix(entry, "DEMO_PORT=")
		}
	}
	return ""
}

func awaitGoConsulSnapshot(t *testing.T, child *exec.Cmd, origin, previousHash string) string {
	t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if child.ProcessState != nil {
			t.Fatalf("Go Runtime exited while waiting for Consul snapshot: %v", child.ProcessState)
		}
		if response, err := http.Get(origin + "/rules"); err == nil {
			body, _ := io.ReadAll(response.Body)
			_ = response.Body.Close()
			value := goAcceptanceValue(t, string(body), "source_bytes_sha256")
			if response.StatusCode == http.StatusOK && value != "" && value != previousHash {
				return string(body)
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("timed out waiting for a changed Consul rule snapshot")
	return ""
}

func consulKVExists(endpoint, key string) (bool, error) {
	request, _ := http.NewRequest(http.MethodGet, consulKVURL(endpoint, key)+"?raw=true", nil)
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return false, err
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNotFound {
		return false, nil
	}
	if response.StatusCode != http.StatusOK {
		return false, fmt.Errorf("Consul key check returned status %d", response.StatusCode)
	}
	return true, nil
}

func consulKVPut(endpoint, key, content string) error {
	request, err := http.NewRequest(http.MethodPut, consulKVURL(endpoint, key), strings.NewReader(content))
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(response.Body)
	if response.StatusCode != http.StatusOK || strings.TrimSpace(string(body)) != "true" {
		return fmt.Errorf("Consul KV publish failed with status %d", response.StatusCode)
	}
	return nil
}

func consulKVDelete(endpoint, key string) error {
	request, err := http.NewRequest(http.MethodDelete, consulKVURL(endpoint, key), nil)
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(response.Body)
	if response.StatusCode != http.StatusOK || strings.TrimSpace(string(body)) != "true" {
		return fmt.Errorf("Consul KV delete failed with status %d", response.StatusCode)
	}
	return nil
}

func consulKVURL(endpoint, key string) string {
	segments := strings.Split(key, "/")
	for index, segment := range segments {
		segments[index] = url.PathEscape(segment)
	}
	return strings.TrimRight(endpoint, "/") + "/v1/kv/" + strings.Join(segments, "/")
}
