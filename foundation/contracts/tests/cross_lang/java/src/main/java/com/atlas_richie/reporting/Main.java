// Main.java: Java CLI entry for the V1 reporting mock codec.
//
// Usage:
//
//   java -jar reporting-mock.jar -kind envelope < input.json > output.json
//   java -jar reporting-mock.jar -kind batch    < input.json > output.json
//   java -jar reporting-mock.jar -kind ack      < input.json > output.json
//   java -jar reporting-mock.jar -kind error    < input.json > output.json
//
// Reads JSON bytes from stdin, decodes + validates + re-encodes to stdout.
// On any validation error, prints a JSON error envelope to stdout and exits 1.
package com.atlas_richie.reporting;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.Map;

public final class Main {

    private Main() {}

    public static void main(String[] args) throws IOException {
        String kind = "envelope";
        for (int i = 0; i < args.length; i++) {
            if ("-kind".equals(args[i]) && i + 1 < args.length) {
                kind = args[i + 1];
                i++;
            }
        }
        byte[] raw = readAll(System.in);
        try {
            switch (kind) {
                case "envelope": {
                    Map<String, Object> e = Codec.decodeEnvelope(raw);
                    byte[] eBytes = Codec.encodeEnvelope(e);
                    System.out.write(eBytes);
                    System.out.write('\n');
                    System.out.flush();
                    return;
                }
                case "batch": {
                    Map<String, Object> b = Codec.decodeBatch(raw);
                    byte[] bBytes = Codec.encodeBatch(b);
                    System.out.write(bBytes);
                    System.out.write('\n');
                    System.out.flush();
                    return;
                }
                case "ack": {
                    Map<String, Object> a = Codec.decodeAck(raw);
                    byte[] aBytes = Codec.encodeAck(a);
                    System.out.write(aBytes);
                    System.out.write('\n');
                    System.out.flush();
                    return;
                }
                case "error": {
                    Map<String, Object> er = Codec.decodeErrorEnvelope(raw);
                    byte[] erBytes = Codec.encodeErrorEnvelope(er);
                    System.out.write(erBytes);
                    System.out.write('\n');
                    System.out.flush();
                    return;
                }
                default:
                    failAndExit("MALFORMED_ENVELOPE",
                        "unknown -kind=" + kind + " (expect envelope|batch|ack|error)");
                    return;
            }
        } catch (CodecException ex) {
            failAndExit(ex.getCode(), ex.getMessage());
        }
    }

    private static byte[] readAll(InputStream in) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int n;
        while ((n = in.read(chunk)) > 0) {
            buf.write(chunk, 0, n);
        }
        return buf.toByteArray();
    }

    private static void failAndExit(String code, String msg) {
        Map<String, Object> obj = new LinkedHashMap<>();
        obj.put("protocol_version", Codec.PROTOCOL_VERSION);
        obj.put("error_code", code);
        obj.put("message", msg);
        obj.put("details", null);
        try {
            byte[] out = Codec.encodeErrorEnvelope(obj);
            System.out.write(out);
            System.out.write('\n');
            System.out.flush();
        } catch (Exception e) {
            String s = "{\"protocol_version\":\"" + Codec.PROTOCOL_VERSION +
                "\",\"error_code\":\"" + code +
                "\",\"message\":\"" + msg +
                "\",\"details\":null}\n";
            System.out.print(s);
            System.out.flush();
        }
        System.exit(1);
    }
}
