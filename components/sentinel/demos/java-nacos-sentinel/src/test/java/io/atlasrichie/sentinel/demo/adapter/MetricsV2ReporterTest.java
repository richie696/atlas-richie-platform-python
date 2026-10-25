package io.atlasrichie.sentinel.demo.adapter;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class MetricsV2ReporterTest {
    @Test
    void rejectedHttpStatusIsObservableWithoutLoggingSnapshotData() {
        String message = MetricsV2Reporter.rejectedHttpStatusMessage(409);

        assertEquals(
                "Metrics V2 durable ACK rejected; response_status=409; exact snapshot retained for retry",
                message);
        assertFalse(message.contains("reporter"));
        assertFalse(message.contains("certificate"));
        assertFalse(message.contains("private-reporter"));
    }
}
