package io.atlasrichie.sentinel.demo.source;

/** Stable provider-read failure without credentials, payloads, or raw response text. */
public final class RuleSourceReadFailure extends Exception {
    public enum Kind { MISSING, REJECTED, UNAVAILABLE }

    private final Kind kind;

    public RuleSourceReadFailure(Kind kind) {
        super("rule source read failed: " + kind.name().toLowerCase());
        this.kind = kind;
    }

    public Kind kind() {
        return kind;
    }
}
