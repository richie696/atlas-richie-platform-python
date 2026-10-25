# T03.5 shared Rule Load Observation V1 fixture conformance

## Purpose

Run the same language-neutral positive and negative JSON fixture corpus through Python, Go, and Java validators. This is contract conformance evidence only: the Go and Java validators in `foundation/contracts/tests/rules/load_observation_v1` are test utilities, not production Runtime SDKs or transport clients.

## Risk-to-test matrix

| ID | Risk | Fixture / assertion | Required evidence |
|---|---|---|---|
| T03.5-X01 | Languages disagree on accepted V1 payload shape | `valid_applied`, `valid_failed_keeps_lkg`, `valid_heartbeat_unknown` accepted; event kind and active/LKG/attempt invariants remain intact | Python, Go, Java pass the same files |
| T03.5-X02 | Unknown or unsupported fields are silently accepted | `invalid_unknown_field`, `invalid_wrong_protocol`, unknown enum, wrong type reject | Python, Go, Java reject each shared file |
| T03.5-X03 | Failure/partial-membership states are misrepresented | failed candidate without attempt and incomplete membership with listed members reject | Python, Go, Java reject each shared file |
| T03.5-X04 | Parser differences allow ambiguous or unsafe JSON | Duplicate object key, unsafe/fractional sequence, invalid UUID/time and trailing JSON reject | Add shared adversarial fixtures; each language rejects |
| T03.5-X05 | Fixture corpus drifts or one runner skips silently | Each runner enumerates all `.json` files and asserts every name is classified exactly once; Python integration test invokes both language suites when toolchains exist | Pytest reports explicit pass or explicit toolchain skip; release closure requires both languages available |

## Boundaries

- Fixture validation does not prove an official Java/Go SDK loads or applies a rule; that belongs to T00.4/T00.5.
- It does not prove mTLS, SQL dialect behavior, ACK durability, or browser rendering.
- Fixtures contain only synthetic IDs and digests; no runtime credentials, raw rules, or production data.
