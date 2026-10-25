package io.atlasrichie.sentinel.demo.source;

import com.alibaba.nacos.api.NacosFactory;
import com.alibaba.nacos.api.config.ConfigService;

import java.util.Properties;

/** Adapts the official Nacos Java client to the Runtime snapshot-source contract. */
final class NacosRuleSnapshotSource implements RuleSnapshotSource {
    private final ConfigService client;
    private final String dataId;
    private final String group;

    private NacosRuleSnapshotSource(ConfigService client, String dataId, String group) {
        this.client = client;
        this.dataId = dataId;
        this.group = group;
    }

    static NacosRuleSnapshotSource fromEnvironment() throws Exception {
        Properties properties = new Properties();
        properties.setProperty("serverAddr", setting("NACOS_SERVER_ADDR", "127.0.0.1:8848"));
        properties.setProperty("namespace", setting("NACOS_NAMESPACE", "public"));
        String username = System.getenv("NACOS_USERNAME");
        String password = System.getenv("NACOS_PASSWORD");
        if (!"false".equalsIgnoreCase(setting("NACOS_AUTH_ENABLED", "true"))) {
            properties.setProperty("username", username == null || username.isBlank() ? "nacos" : username);
            properties.setProperty("password", password == null || password.isBlank()
                    ? required("NACOS_PASSWORD") : password);
        }
        properties.setProperty("cacheDir", setting("NACOS_CACHE_DIR", ".nacos-cache"));
        properties.setProperty("logDir", setting("NACOS_LOG_DIR", ".nacos-log"));
        ConfigService client = NacosFactory.createConfigService(properties);
        return new NacosRuleSnapshotSource(client,
                setting("NACOS_DATA_ID", "sentinel-e2e-20261017-java-flow-rules.json"),
                setting("NACOS_GROUP", "DEFAULT_GROUP"));
    }

    @Override
    public String read() throws Exception {
        return client.getConfig(dataId, group, 5_000L);
    }

    @Override
    public void close() throws Exception {
        client.shutDown();
    }

    private static String setting(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private static String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) throw new IllegalStateException(name + " is required");
        return value;
    }
}
