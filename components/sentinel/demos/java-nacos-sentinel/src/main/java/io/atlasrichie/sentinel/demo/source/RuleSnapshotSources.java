package io.atlasrichie.sentinel.demo.source;

/** Composition-root selection for the configured rule-source provider. */
public final class RuleSnapshotSources {
    private RuleSnapshotSources() { }

    public static RuleSnapshotSource fromEnvironment() throws Exception {
        String provider = System.getenv("RULE_SOURCE_PROVIDER");
        if (provider == null || provider.isBlank() || provider.equals("nacos")) {
            return NacosRuleSnapshotSource.fromEnvironment();
        }
        if (provider.equals("consul")) return ConsulRuleSnapshotSource.fromEnvironment();
        throw new IllegalStateException("unsupported RULE_SOURCE_PROVIDER");
    }
}
