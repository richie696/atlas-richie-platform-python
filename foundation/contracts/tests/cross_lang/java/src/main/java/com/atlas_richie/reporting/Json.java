// Json.java: minimal stdlib-only JSON parser + serializer.
//
// Java has no built-in JSON, and the brief prohibits third-party runtime
// dependencies. This file implements just enough of RFC 8259 to round-trip
// the data shapes the V1 reporting protocol carries.
package com.atlas_richie.reporting;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class Json {

    private Json() {}

    public static Object parse(byte[] raw) throws CodecException {
        return parse(new String(raw, java.nio.charset.StandardCharsets.UTF_8));
    }

    public static Object parse(String s) throws CodecException {
        Parser p = new Parser(s);
        p.skipWs();
        Object v = p.parseValue();
        p.skipWs();
        if (p.pos < p.src.length()) {
            throw new CodecException("MALFORMED_ENVELOPE",
                "trailing content at position " + p.pos);
        }
        return v;
    }

    private static final class Parser {
        final String src;
        int pos;

        Parser(String src) {
            this.src = src;
            this.pos = 0;
        }

        void skipWs() {
            while (pos < src.length() && Character.isWhitespace(src.charAt(pos))) {
                pos++;
            }
        }

        Object parseValue() throws CodecException {
            skipWs();
            if (pos >= src.length()) {
                throw new CodecException("MALFORMED_ENVELOPE", "unexpected end of input");
            }
            char c = src.charAt(pos);
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't' || c == 'f') return parseBool();
            if (c == 'n') return parseNull();
            if (c == '-' || (c >= '0' && c <= '9')) return parseNumber();
            throw new CodecException("MALFORMED_ENVELOPE",
                "unexpected char '" + c + "' at position " + pos);
        }

        Map<String, Object> parseObject() throws CodecException {
            expect('{');
            Map<String, Object> out = new LinkedHashMap<>();
            skipWs();
            if (peek() == '}') {
                pos++;
                return out;
            }
            while (true) {
                skipWs();
                String key = parseString();
                skipWs();
                expect(':');
                Object value = parseValue();
                out.put(key, value);
                skipWs();
                char c = peek();
                if (c == ',') {
                    pos++;
                    continue;
                }
                if (c == '}') {
                    pos++;
                    return out;
                }
                throw new CodecException("MALFORMED_ENVELOPE",
                    "expected ',' or '}' at position " + pos);
            }
        }

        List<Object> parseArray() throws CodecException {
            expect('[');
            List<Object> out = new ArrayList<>();
            skipWs();
            if (peek() == ']') {
                pos++;
                return out;
            }
            while (true) {
                Object v = parseValue();
                out.add(v);
                skipWs();
                char c = peek();
                if (c == ',') {
                    pos++;
                    continue;
                }
                if (c == ']') {
                    pos++;
                    return out;
                }
                throw new CodecException("MALFORMED_ENVELOPE",
                    "expected ',' or ']' at position " + pos);
            }
        }

        String parseString() throws CodecException {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (pos < src.length()) {
                char c = src.charAt(pos++);
                if (c == '"') {
                    return sb.toString();
                }
                if (c == '\\') {
                    if (pos >= src.length()) {
                        throw new CodecException("MALFORMED_ENVELOPE",
                            "unterminated string escape");
                    }
                    char esc = src.charAt(pos++);
                    switch (esc) {
                        case '"':  sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/':  sb.append('/'); break;
                        case 'b':  sb.append('\b'); break;
                        case 'f':  sb.append('\f'); break;
                        case 'n':  sb.append('\n'); break;
                        case 'r':  sb.append('\r'); break;
                        case 't':  sb.append('\t'); break;
                        case 'u':
                            if (pos + 4 > src.length()) {
                                throw new CodecException("MALFORMED_ENVELOPE",
                                    "short \\u escape");
                            }
                            int cp = Integer.parseInt(src.substring(pos, pos + 4), 16);
                            sb.append((char) cp);
                            pos += 4;
                            break;
                        default:
                            throw new CodecException("MALFORMED_ENVELOPE",
                                "invalid escape \\" + esc);
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new CodecException("MALFORMED_ENVELOPE", "unterminated string");
        }

        Object parseNumber() throws CodecException {
            int start = pos;
            if (peek() == '-') pos++;
            while (pos < src.length() && Character.isDigit(src.charAt(pos))) {
                pos++;
            }
            if (pos < src.length()) {
                char c = src.charAt(pos);
                if (c == '.' || c == 'e' || c == 'E' || c == '+') {
                    throw new CodecException("MALFORMED_ENVELOPE",
                        "non-integer numbers are not allowed (V1 uses int64 only) at position " + start);
                }
            }
            String numStr = src.substring(start, pos);
            try {
                return Long.parseLong(numStr);
            } catch (NumberFormatException e) {
                throw new CodecException("MALFORMED_ENVELOPE",
                    "invalid integer '" + numStr + "' at position " + start);
            }
        }

        Boolean parseBool() throws CodecException {
            if (src.startsWith("true", pos)) {
                pos += 4;
                return Boolean.TRUE;
            }
            if (src.startsWith("false", pos)) {
                pos += 5;
                return Boolean.FALSE;
            }
            throw new CodecException("MALFORMED_ENVELOPE",
                "expected true/false at position " + pos);
        }

        Object parseNull() throws CodecException {
            if (src.startsWith("null", pos)) {
                pos += 4;
                return null;
            }
            throw new CodecException("MALFORMED_ENVELOPE",
                "expected null at position " + pos);
        }

        void expect(char c) throws CodecException {
            if (pos >= src.length() || src.charAt(pos) != c) {
                throw new CodecException("MALFORMED_ENVELOPE",
                    "expected '" + c + "' at position " + pos);
            }
            pos++;
        }

        char peek() {
            if (pos >= src.length()) return '\0';
            return src.charAt(pos);
        }
    }

    public static byte[] write(Object v) throws CodecException {
        StringBuilder sb = new StringBuilder();
        writeValue(sb, v);
        return sb.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
    }

    @SuppressWarnings("unchecked")
    private static void writeValue(StringBuilder sb, Object v) throws CodecException {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof Boolean) {
            sb.append(((Boolean) v) ? "true" : "false");
        } else if (v instanceof Long) {
            sb.append(v.toString());
        } else if (v instanceof Integer) {
            sb.append(v.toString());
        } else if (v instanceof String) {
            writeString(sb, (String) v);
        } else if (v instanceof Map) {
            writeObject(sb, (Map<String, Object>) v);
        } else if (v instanceof List) {
            writeArray(sb, (List<Object>) v);
        } else {
            throw new CodecException("MALFORMED_ENVELOPE",
                "unsupported value type: " + v.getClass().getName());
        }
    }

    private static void writeObject(StringBuilder sb, Map<String, Object> obj)
            throws CodecException {
        sb.append('{');
        boolean first = true;
        for (Map.Entry<String, Object> e : obj.entrySet()) {
            if (!first) sb.append(',');
            first = false;
            writeString(sb, e.getKey());
            sb.append(':');
            writeValue(sb, e.getValue());
        }
        sb.append('}');
    }

    private static void writeArray(StringBuilder sb, List<Object> arr)
            throws CodecException {
        sb.append('[');
        boolean first = true;
        for (Object v : arr) {
            if (!first) sb.append(',');
            first = false;
            writeValue(sb, v);
        }
        sb.append(']');
    }

    private static void writeString(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        sb.append('"');
    }
}
