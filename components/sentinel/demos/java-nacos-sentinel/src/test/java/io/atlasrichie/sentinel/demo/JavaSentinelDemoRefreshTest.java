package io.atlasrichie.sentinel.demo;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class JavaSentinelDemoRefreshTest {
    @Test
    void reportsRecoveryWhenProviderReturnsTheAlreadyActiveSnapshotAfterFailure() {
        String accepted = "[{\"resource\":\"orders\",\"grade\":1,\"count\":1}]";
        String rejected = "[{\"resource\":\"orders\",\"grade\":1,\"count\":9,\"unknown\":true}]";

        assertTrue(JavaSentinelDemo.shouldReportSnapshotRecovery(
                accepted, accepted, rejected, "decode_rejected"));
        assertTrue(JavaSentinelDemo.shouldReportSnapshotRecovery(
                accepted, accepted, "", "source_unavailable"));
    }

    @Test
    void doesNotReportRecoveryWithoutAnAcceptedSnapshotFailureOrOnRejectedContent() {
        String accepted = "[{\"resource\":\"orders\",\"grade\":1,\"count\":1}]";
        String rejected = "[{\"resource\":\"orders\",\"grade\":1,\"count\":9,\"unknown\":true}]";

        assertFalse(JavaSentinelDemo.shouldReportSnapshotRecovery(
                accepted, accepted, "", ""));
        assertFalse(JavaSentinelDemo.shouldReportSnapshotRecovery(
                rejected, accepted, rejected, "decode_rejected"));
        assertFalse(JavaSentinelDemo.shouldReportSnapshotRecovery(
                null, accepted, "", "source_unavailable"));
    }
}
