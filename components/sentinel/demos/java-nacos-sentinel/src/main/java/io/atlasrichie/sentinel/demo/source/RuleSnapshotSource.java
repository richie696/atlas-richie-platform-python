package io.atlasrichie.sentinel.demo.source;

/** Reads one complete rule snapshot from the explicitly selected provider. */
public interface RuleSnapshotSource extends AutoCloseable {
    /** Read the current snapshot; errors must not be converted into an empty rule set. */
    String read() throws Exception;

    /** Release provider-owned resources. */
    @Override
    void close() throws Exception;
}
