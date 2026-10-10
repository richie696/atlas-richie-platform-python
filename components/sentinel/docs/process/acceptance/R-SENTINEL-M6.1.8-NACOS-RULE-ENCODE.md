# M6.1.8 Nacos rule snapshot encoder

## Scope

Add the pure reverse mapping for the existing Nacos codec: a typed Sentinel
`RuleSnapshot` becomes the five configured Nacos rule data-id JSON documents.
The encoder extends the existing codec boundary; it adds no strategy, factory,
or transport abstraction.

This slice does **not** call Nacos, publish configuration, provide CAS, read the
published value back, persist a Console validation receipt, or implement the
Consul profile. Its round-trip tests prove only compatibility with this
Python codec, not Java client interoperability. Console `validate` must stay
unavailable until a validator can prove the selected profile and baseline and
bind its receipt to an immutable candidate.

## Behavior

- Returns exactly the five configured data-id keys, including `[]` for empty
  rule kinds.
- Emits deterministic compact UTF-8 JSON with sorted object keys and rule IDs.
- Maps all five current Sentinel rule families using the profile's integer enum
  conventions.
- Rejects unsupported rule types, mismatched mapping/rule IDs, non-finite JSON
  values, and flow behavior/control combinations that share one Nacos field but
  cannot round-trip exactly.
- `NacosEncodeError` carries only `data_id` and `rule_id`; it does not include
  rule content, credentials, or network information.
- Exported API additions: `encode_rule_snapshot` and `NacosEncodeError`. Existing
  decode and source lifecycle signatures are unchanged.

## Risk-to-test matrix

| Risk | Evidence |
| --- | --- |
| A field is silently lost across five codecs | Decode → encode → decode equality test with all five kinds and optional fields populated |
| Repeated writes vary by process/dict order | Repeat encoding and assert byte-for-byte stable output and all five keys |
| Unsupported flow semantics are incorrectly marked writable | Unrepresentable behavior/control pair raises `NacosEncodeError` |
| JSON accepts NaN/Infinity | Non-finite threshold is rejected during strict JSON serialization |
| Provider SDK leaks into pure codec | Existing API/source isolation tests remain green; function signature contains no SDK type |
| Existing polling/decode behavior regresses | Nacos codec plus source focused unit suite |

## Verification

- `pytest -q tests/test_sen_nacos_codec.py tests/test_sen_nacos_source.py`: **82 passed**.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed.
- No real Nacos instance, SDK write call, live Console, or browser E2E was used.
  These remain separate B0.3/B0.5 and final-milestone evidence.

## Remaining work

Implement profile-bound Console validation and durable receipts, then source
conditional publication/CAS/read-back and Consul-compatible codec/provider
support. Only after those are integrated can a source-specific publish path
claim `isPublishable`.
