// CodecException.java: strict codec error type. Mirrors Python's
// ReportingProtocolError.
package com.atlas_richie.reporting;

public class CodecException extends Exception {
    private final String code;

    public CodecException(String code, String message) {
        super("[" + code + "] " + message);
        this.code = code;
    }

    public String getCode() {
        return code;
    }
}
