package main

import (
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/nacos-group/nacos-sdk-go/v2/clients"
	"github.com/nacos-group/nacos-sdk-go/v2/common/constant"
	"github.com/nacos-group/nacos-sdk-go/v2/model"
	"github.com/nacos-group/nacos-sdk-go/v2/vo"
)

func TestRealNacosPollingRuntimeAcceptance(t *testing.T) {
	if os.Getenv("SENTINEL_T004_GO_NACOS_ACCEPTANCE") != "true" {
		t.Skip("set SENTINEL_T004_GO_NACOS_ACCEPTANCE=true to run against the configured Nacos instance")
	}
	authEnabled := strings.ToLower(strings.TrimSpace(os.Getenv("NACOS_AUTH_ENABLED"))) != "false"
	if !authEnabled && os.Getenv("SENTINEL_T004_DISPOSABLE_NACOS") != "true" {
		t.Fatal("disabling Nacos auth is allowed only for an explicitly disposable acceptance provider")
	}
	password := strings.TrimSpace(os.Getenv("NACOS_PASSWORD"))
	if authEnabled && password == "" {
		t.Fatal("NACOS_PASSWORD must be provided through the local secret environment")
	}
	serverAddr := setting("NACOS_SERVER_ADDR", "127.0.0.1")
	serverPort := uint64(numberSetting("NACOS_SERVER_PORT", 8848))
	namespace := setting("NACOS_NAMESPACE", "public")
	group := setting("NACOS_GROUP", "DEFAULT_GROUP")
	username := ""
	if authEnabled {
		username = setting("NACOS_USERNAME", "nacos")
	} else {
		password = ""
	}
	dataID := fmt.Sprintf("sentinel-t004-go-acceptance-%d-flow-rules.json", time.Now().UnixNano())
	cacheDir := t.TempDir()
	publisher, err := clients.NewConfigClient(vo.NacosClientParam{
		ClientConfig: &constant.ClientConfig{
			TimeoutMs: 5000, NamespaceId: namespace, Username: username, Password: password,
			NotLoadCacheAtStart: true, DisableUseSnapShot: true, LogLevel: "warn",
			CacheDir: filepath.Join(cacheDir, "publisher-cache"), LogDir: filepath.Join(cacheDir, "publisher-log"),
		},
		ServerConfigs: []constant.ServerConfig{{IpAddr: serverAddr, Port: serverPort, ContextPath: "/nacos"}},
	})
	if err != nil {
		t.Fatalf("create Nacos acceptance client: %v", err)
	}
	defer publisher.CloseClient()

	config := vo.ConfigParam{DataId: dataID, Group: group}
	existing, err := publisher.GetConfig(config)
	if err != nil {
		t.Fatalf("check random acceptance Data ID: %v", err)
	}
	if existing != "" {
		t.Fatal("random acceptance Data ID was unexpectedly occupied; refusing to overwrite it")
	}
	created := false
	defer func() {
		if os.Getenv("SENTINEL_T004_DISPOSABLE_NACOS") == "true" {
			// The caller owns this no-volume provider and removes the exact container
			// after the test; cleanup must not probe auth-protected search APIs.
			return
		}
		if created {
			if goAcceptanceConfigExists(t, publisher, dataID, group) {
				deleted, deleteErr := publisher.DeleteConfig(config)
				if deleteErr != nil || !deleted {
					t.Errorf("delete only this test's temporary Nacos Data ID: deleted=%t err=%v", deleted, deleteErr)
				}
			}
			deadline := time.Now().Add(5 * time.Second)
			for goAcceptanceConfigExists(t, publisher, dataID, group) && time.Now().Before(deadline) {
				time.Sleep(100 * time.Millisecond)
			}
			if goAcceptanceConfigExists(t, publisher, dataID, group) {
				t.Error("test-owned Nacos Data ID remains in provider search after cleanup")
			}
		}
	}()

	created = true
	if _, err := publishGoAcceptanceConfig(publisher, config, goAcceptanceRules(1)); err != nil {
		t.Fatalf("publish initial test-owned Nacos rules: %v", err)
	}
	port := unusedGoAcceptancePort(t)
	runtimeDir := t.TempDir()
	binary := filepath.Join(runtimeDir, "sentinel-go-acceptance")
	build := exec.Command("go", "build", "-o", binary, ".")
	build.Dir = "."
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build Go acceptance runtime: %v\n%s", err, output)
	}
	logFile, err := os.Create(filepath.Join(runtimeDir, "runtime.log"))
	if err != nil {
		t.Fatal(err)
	}
	defer logFile.Close()
	runtimeEnv := goAcceptanceEnvironment(os.Environ(), map[string]string{
		"NACOS_SERVER_ADDR": serverAddr, "NACOS_SERVER_PORT": fmt.Sprint(serverPort),
		"NACOS_NAMESPACE": namespace, "NACOS_GROUP": group, "NACOS_USERNAME": username,
		"NACOS_PASSWORD": password, "NACOS_AUTH_ENABLED": fmt.Sprint(authEnabled), "NACOS_DATA_ID": dataID,
		"SENTINEL_T004_DISPOSABLE_NACOS": "true",
		"NACOS_CACHE_DIR":                filepath.Join(runtimeDir, "runtime-cache"),
		"NACOS_LOG_DIR":                  filepath.Join(runtimeDir, "runtime-nacos-log"),
		"SENTINEL_LOG_DIR":               filepath.Join(runtimeDir, "runtime-sentinel-log"),
		"DEMO_BIND_HOST":                 "127.0.0.1", "DEMO_PORT": fmt.Sprint(port),
		"RULE_SOURCE_PROFILE": "native-array-v1",
	})
	child := exec.Command(binary)
	child.Dir = runtimeDir
	child.Env = runtimeEnv
	child.Stdout, child.Stderr = logFile, logFile
	if err := child.Start(); err != nil {
		t.Fatalf("start isolated Go runtime: %v", err)
	}
	defer func() {
		if child.Process != nil {
			_ = child.Process.Kill()
			_, _ = child.Process.Wait()
		}
	}()
	origin := fmt.Sprintf("http://127.0.0.1:%d", port)
	awaitGoAcceptanceHealth(t, child, origin)
	initial := awaitGoAcceptanceSnapshot(t, child, origin, "")
	initialHash := goAcceptanceValue(t, initial, "source_bytes_sha256")
	if got := goAcceptanceBurst(t, origin, 8); !containsInt(got, http.StatusTooManyRequests) || !containsInt(got, http.StatusOK) {
		t.Fatalf("strict official Sentinel rule should admit and block requests, got %v", got)
	}
	if _, err := publishGoAcceptanceConfig(publisher, config, goAcceptanceRules(100)); err != nil {
		t.Fatalf("publish valid rule update: %v", err)
	}
	updated := awaitGoAcceptanceSnapshot(t, child, origin, initialHash)
	updatedHash := goAcceptanceValue(t, updated, "source_bytes_sha256")
	if statuses := goAcceptanceBurst(t, origin, 8); !allStatuses(statuses, http.StatusOK) {
		t.Fatalf("updated high threshold should admit the bounded burst, got %v", statuses)
	}
	if _, err := publishGoAcceptanceConfig(publisher, config, goAcceptanceInvalidRules()); err != nil {
		t.Fatalf("publish invalid candidate: %v", err)
	}
	awaitGoAcceptanceLog(t, logFile.Name(), "polled rule update rejected: invalid_rules")
	if got := goAcceptanceReadRules(t, origin); goAcceptanceValue(t, got, "source_bytes_sha256") != updatedHash {
		t.Fatal("invalid candidate replaced the active last-known-good snapshot")
	}
	if statuses := goAcceptanceBurst(t, origin, 8); !allStatuses(statuses, http.StatusOK) {
		t.Fatalf("last-known-good high threshold should remain active, got %v", statuses)
	}
	previousRejectedLogs := goAcceptanceLogCount(t, logFile.Name(), "polled rule update rejected: invalid_rules")
	if deleted, err := publisher.DeleteConfig(config); err != nil || !deleted {
		t.Fatalf("temporarily delete only this test-owned Data ID: %v", err)
	}
	awaitGoAcceptanceLogCount(t, logFile.Name(), "polled rule update rejected: invalid_rules", previousRejectedLogs+1)
	if _, err := publishGoAcceptanceConfig(publisher, config, goAcceptanceRules(2)); err != nil {
		t.Fatalf("republish valid rules after temporary removal: %v", err)
	}
	recovered := awaitGoAcceptanceSnapshot(t, child, origin, updatedHash)
	if goAcceptanceValue(t, recovered, "source_bytes_sha256") == initialHash {
		t.Fatal("recovery must apply a new provider snapshot")
	}
	if statuses := goAcceptanceBurst(t, origin, 8); !containsInt(statuses, http.StatusTooManyRequests) {
		t.Fatalf("recovered restrictive snapshot should be enforced, got %v", statuses)
	}
	if os.Getenv("SENTINEL_T004_DISPOSABLE_NACOS") == "true" {
		resumeNacos := pauseGoAcceptanceNacos(t)
		awaitGoAcceptanceLogWithin(t, logFile.Name(), "rule source unavailable; retaining last-known-good rules", 20*time.Second)
		if got := goAcceptanceReadRules(t, origin); goAcceptanceValue(t, got, "source_bytes_sha256") != goAcceptanceValue(t, recovered, "source_bytes_sha256") {
			t.Fatal("Nacos transport outage must not replace the active last-known-good snapshot")
		}
		if statuses := goAcceptanceBurst(t, origin, 8); !containsInt(statuses, http.StatusTooManyRequests) {
			t.Fatalf("the active restrictive rule must remain enforced while Nacos is unavailable, got %v", statuses)
		}
		resumeNacos()
		awaitGoAcceptanceLogWithin(t, logFile.Name(), "rule source recovered; retained active snapshot", 20*time.Second)
		if got := goAcceptanceReadRules(t, origin); goAcceptanceValue(t, got, "source_bytes_sha256") != goAcceptanceValue(t, recovered, "source_bytes_sha256") {
			t.Fatal("recovered provider must revalidate and retain the same active snapshot")
		}
		if statuses := goAcceptanceBurst(t, origin, 8); !containsInt(statuses, http.StatusTooManyRequests) {
			t.Fatalf("the revalidated rule must remain enforced after Nacos recovers, got %v", statuses)
		}
	}
	if err := child.Process.Kill(); err != nil {
		t.Fatalf("stop isolated Go runtime before restart acceptance: %v", err)
	}
	// Wait returns an ExitError for the SIGKILL we just requested; it still
	// reaps the exact test-owned process before the replacement binds a port.
	_ = child.Wait()
	if child.ProcessState == nil {
		t.Fatal("isolated Go runtime was not reaped before restart acceptance")
	}
	restartedPort := unusedGoAcceptancePort(t)
	restartedEnv := goAcceptanceEnvironment(os.Environ(), map[string]string{
		"NACOS_SERVER_ADDR": serverAddr, "NACOS_SERVER_PORT": fmt.Sprint(serverPort),
		"NACOS_NAMESPACE": namespace, "NACOS_GROUP": group, "NACOS_USERNAME": username,
		"NACOS_PASSWORD": password, "NACOS_AUTH_ENABLED": fmt.Sprint(authEnabled), "NACOS_DATA_ID": dataID,
		"SENTINEL_T004_DISPOSABLE_NACOS": "true",
		"NACOS_CACHE_DIR":                filepath.Join(runtimeDir, "runtime-cache-restarted"),
		"NACOS_LOG_DIR":                  filepath.Join(runtimeDir, "runtime-nacos-log-restarted"),
		"SENTINEL_LOG_DIR":               filepath.Join(runtimeDir, "runtime-sentinel-log-restarted"),
		"DEMO_BIND_HOST":                 "127.0.0.1", "DEMO_PORT": fmt.Sprint(restartedPort),
		"RULE_SOURCE_PROFILE": "native-array-v1",
	})
	child = exec.Command(binary)
	child.Dir = runtimeDir
	child.Env = restartedEnv
	child.Stdout, child.Stderr = logFile, logFile
	if err := child.Start(); err != nil {
		t.Fatalf("restart isolated Go runtime: %v", err)
	}
	restartedOrigin := fmt.Sprintf("http://127.0.0.1:%d", restartedPort)
	awaitGoAcceptanceHealth(t, child, restartedOrigin)
	restarted := awaitGoAcceptanceSnapshot(t, child, restartedOrigin, "")
	if got := goAcceptanceValue(t, restarted, "source_bytes_sha256"); got != goAcceptanceValue(t, recovered, "source_bytes_sha256") {
		t.Fatalf("restarted Go runtime must load the persisted provider snapshot before business traffic: got %s, want %s",
			got, goAcceptanceValue(t, recovered, "source_bytes_sha256"))
	}
	if statuses := goAcceptanceBurst(t, restartedOrigin, 8); !containsInt(statuses, http.StatusTooManyRequests) {
		t.Fatalf("restarted runtime must execute the recovered restrictive rule, got %v", statuses)
	}
}

func publishGoAcceptanceConfig(client interface {
	PublishConfig(vo.ConfigParam) (bool, error)
}, config vo.ConfigParam, content string) (bool, error) {
	config.Content = content
	return client.PublishConfig(config)
}

func goAcceptanceConfigExists(t *testing.T, client interface {
	SearchConfig(vo.SearchConfigParam) (*model.ConfigPage, error)
}, dataID, group string) bool {
	t.Helper()
	page, err := client.SearchConfig(vo.SearchConfigParam{
		Search: "accurate", DataId: dataID, Group: group, PageNo: 1, PageSize: 10,
	})
	if err != nil {
		t.Errorf("search only the test-owned Nacos Data ID: %v", err)
		return true
	}
	return page != nil && len(page.PageItems) != 0
}

func goAcceptanceEnvironment(current []string, overrides map[string]string) []string {
	removed := map[string]struct{}{
		"METRICS_COLLECTOR_URL": {}, "METRICS_REPORTER_ID": {}, "METRICS_CLIENT_CERT": {},
		"METRICS_CLIENT_KEY": {}, "METRICS_COLLECTOR_CA": {}, "RULE_BINDING_ID": {},
		"SENTINEL_T004_DISPOSABLE_NACOS": {}, "NACOS_AUTH_ENABLED": {},
	}
	for key := range overrides {
		removed[key] = struct{}{}
	}
	env := make([]string, 0, len(current)+len(overrides))
	for _, entry := range current {
		key, _, _ := strings.Cut(entry, "=")
		if _, skip := removed[key]; !skip {
			env = append(env, entry)
		}
	}
	for key, value := range overrides {
		env = append(env, key+"="+value)
	}
	return env
}

func goAcceptanceRules(qps int) string {
	return fmt.Sprintf(`[{"resource":"GET /api/hello","threshold":%d,"statIntervalInMs":1000}]`, qps)
}

func goAcceptanceInvalidRules() string {
	return `[{"resource":"GET /api/hello","threshold":1,"statIntervalInMs":1000,"unknown_acceptance_field":true}]`
}

func awaitGoAcceptanceHealth(t *testing.T, child *exec.Cmd, origin string) {
	t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		if child.ProcessState != nil {
			t.Fatal("Go runtime exited before health became ready")
		}
		response, err := http.Get(origin + "/health")
		if err == nil {
			_ = response.Body.Close()
			if response.StatusCode == http.StatusOK {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("Go runtime did not become healthy before deadline")
}

func awaitGoAcceptanceSnapshot(t *testing.T, child *exec.Cmd, origin, previousHash string) string {
	t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if child.ProcessState != nil {
			t.Fatal("Go runtime exited while awaiting rule snapshot")
		}
		body := goAcceptanceReadRules(t, origin)
		if strings.Contains(body, "rules_loaded=true") && goAcceptanceValue(t, body, "rule_count") == "1" {
			hash := goAcceptanceValue(t, body, "source_bytes_sha256")
			if previousHash == "" || hash != previousHash {
				return body
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("Go runtime did not apply expected snapshot within 20 seconds (previous hash %s)", previousHash)
	return ""
}

func goAcceptanceReadRules(t *testing.T, origin string) string {
	t.Helper()
	response, err := http.Get(origin + "/rules")
	if err != nil {
		t.Fatalf("read runtime rules: %v", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode != http.StatusOK {
		t.Fatalf("read runtime rules returned status %d: %v", response.StatusCode, err)
	}
	return string(body)
}

func goAcceptanceValue(t *testing.T, body, key string) string {
	t.Helper()
	for _, line := range strings.Split(body, "\n") {
		if value, found := strings.CutPrefix(line, key+"="); found {
			return value
		}
	}
	t.Fatalf("runtime rules response omitted %s", key)
	return ""
}

func goAcceptanceBurst(t *testing.T, origin string, count int) []int {
	t.Helper()
	statuses := make([]int, 0, count)
	client := &http.Client{Timeout: 5 * time.Second}
	for range count {
		response, err := client.Get(origin + "/api/hello")
		if err != nil {
			t.Fatalf("call flow-controlled endpoint: %v", err)
		}
		statuses = append(statuses, response.StatusCode)
		_ = response.Body.Close()
	}
	return statuses
}

func awaitGoAcceptanceLog(t *testing.T, path, expected string) {
	t.Helper()
	awaitGoAcceptanceLogWithin(t, path, expected, 5*time.Second)
}

func awaitGoAcceptanceLogWithin(t *testing.T, path, expected string, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		content, err := os.ReadFile(path)
		if err == nil && strings.Contains(string(content), expected) {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("runtime log did not contain the expected sanitized state: %s", expected)
}

func pauseGoAcceptanceNacos(t *testing.T) func() {
	t.Helper()
	containerName := strings.TrimSpace(os.Getenv("SENTINEL_T004_DISPOSABLE_NACOS_CONTAINER"))
	expectedOwner := strings.TrimSpace(os.Getenv("SENTINEL_T004_DISPOSABLE_NACOS_OWNER"))
	if containerName == "" || expectedOwner == "" {
		t.Fatal("network outage acceptance requires the exact disposable Nacos container name and owner label")
	}
	label, err := exec.Command("docker", "inspect", "--format={{index .Config.Labels \"com.atlas-richie.sentinel-t004.run\"}}", containerName).Output()
	if err != nil {
		t.Fatalf("inspect only the declared disposable Nacos container: %v", err)
	}
	if strings.TrimSpace(string(label)) != expectedOwner {
		t.Fatalf("refusing to pause Nacos container with unexpected owner label %q", strings.TrimSpace(string(label)))
	}
	if output, err := exec.Command("docker", "pause", containerName).CombinedOutput(); err != nil {
		t.Fatalf("pause only the declared disposable Nacos container: %v (%s)", err, strings.TrimSpace(string(output)))
	}
	paused := true
	resume := func() {
		if !paused {
			return
		}
		output, err := exec.Command("docker", "unpause", containerName).CombinedOutput()
		if err != nil {
			t.Errorf("resume only the declared disposable Nacos container: %v (%s)", err, strings.TrimSpace(string(output)))
			return
		}
		paused = false
	}
	t.Cleanup(resume)
	return resume
}

func goAcceptanceLogCount(t *testing.T, path, expected string) int {
	t.Helper()
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read isolated runtime log: %v", err)
	}
	return strings.Count(string(content), expected)
}

func awaitGoAcceptanceLogCount(t *testing.T, path, expected string, count int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if goAcceptanceLogCount(t, path, expected) >= count {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("runtime log did not reach expected rejection count %d", count)
}

func unusedGoAcceptancePort(t *testing.T) int {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	return listener.Addr().(*net.TCPAddr).Port
}

func containsInt(values []int, expected int) bool {
	for _, value := range values {
		if value == expected {
			return true
		}
	}
	return false
}

func allStatuses(values []int, expected int) bool {
	if len(values) == 0 {
		return false
	}
	for _, value := range values {
		if value != expected {
			return false
		}
	}
	return true
}

func TestReportsRecoveryWhenProviderReturnsTheAlreadyActiveSnapshotAfterFailure(t *testing.T) {
	accepted := `[{"resource":"orders","threshold":1,"statIntervalInMs":1000}]`
	rejected := `[{"resource":"orders","threshold":9,"statIntervalInMs":500}]`

	if !shouldReportGoSnapshotRecovery(accepted, accepted, rejected, "decode_rejected") {
		t.Fatal("expected recovery event for the revalidated active snapshot")
	}
	if !shouldReportGoSnapshotRecovery(accepted, accepted, "", "source_unavailable") {
		t.Fatal("expected recovery event after source became readable again")
	}
}

func TestDoesNotReportRecoveryWithoutFailureOrForRejectedContent(t *testing.T) {
	accepted := `[{"resource":"orders","threshold":1,"statIntervalInMs":1000}]`
	rejected := `[{"resource":"orders","threshold":9,"statIntervalInMs":500}]`

	if shouldReportGoSnapshotRecovery(accepted, accepted, "", "") {
		t.Fatal("must not repeat snapshot-applied event without a preceding failure")
	}
	if shouldReportGoSnapshotRecovery(rejected, accepted, rejected, "decode_rejected") {
		t.Fatal("rejected candidate must not be treated as recovered")
	}
	if shouldReportGoSnapshotRecovery("", "", "", "source_unavailable") {
		t.Fatal("missing content must not be treated as recovery")
	}
}
