package io.atlasrichie.sentinel.demo.adapter;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class RuleLoadObservationV1ReporterTest {
    @Test
    void rejectedHttpStatusIsObservableWithoutLoggingEventData() {
        String message = RuleLoadObservationV1Reporter.rejectedEventMessage(409);

        assertEquals(
                "Rule Observation Collector rejected event; response_status=409; exact event retained for retry",
                message);
        assertFalse(message.contains("binding"));
        assertFalse(message.contains("certificate"));
        assertFalse(message.contains("payload"));
    }
}
