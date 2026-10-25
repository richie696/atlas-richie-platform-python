---
title: Create and verify your first flow control rule
summary: Complete the whole draft, publish, load and rejection cycle on a test service.
prerequisite: An admin account; a writable source; the correct binding and
  profile; a test service that can issue requests.
outcome: "Produce three independent pieces of evidence: persistence, instance
  loading and actual enforcement."
---

## Confirm three things before you start

Build the first rule on a test service, with a threshold that is easy to observe. Do not start writing until these three points are confirmed.

1. The profile on the binding supports the fields you intend to publish. The current Java and Go profiles only support the one-second QPS direct-rejection subset of flow control.
2. The resource name the rule protects matches the instrumentation in the service character for character. This is the most common cause and the hardest one to self-check.
3. The source can be written, and you already have a known-good version to roll back to.

## Create the draft

The draft is stored in the Console database. Saving a draft does not write to the configuration center, so this step is fully reversible.

1. On the rules page select the target binding and enter the rule workbench.
2. Create a new draft, or open the sample draft to see the field structure first.
3. Fill in the resource name; it must match the instrumentation in the service character for character.
4. Choose threshold type QPS, matching strategy the current resource, and control behavior immediate rejection.
5. Set a test threshold, for example 3.
6. Save the draft. The draft appears in the draft catalog and you can keep editing it at any time.

> **Note** Editing a draft does not lose the other rules — a draft stores the whole rule set. Deleting a draft does not affect the immutable versions or the current rules in the configuration center.

## Validate and freeze the version

Validation is a read-only evaluation: the server checks against the binding profile whether this draft can be published. It writes nothing to the configuration center and it does not freeze a version.

1. Click validate target compatibility.
2. If there are problems, fix them one by one as the message indicates. Pay attention to the rejected fields — a field the profile does not support is not ignored, the whole rule is rejected.
3. After the validation passes, fill in the version name and the version note and save it as an immutable version.
4. In the version catalog, confirm that the new version exists. A version cannot be modified after creation; to adjust it you have to create a new draft based on it.

> **Note** A passing validation does not guarantee that the target runtime supports this content. The server validates the rule against the profile; which profile the runtime actually uses is confirmed by the load observation and the negotiation result.

## Publish and confirm the read-back

Publishing replaces the whole content; it is not an incremental patch. After the publication the console reads the content back independently and compares it.

1. In the version catalog select the target version and click publish the selected version.
2. Confirm the publication. It carries an idempotency key, so resubmitting the same key does not produce a second write.
3. Wait for the three phases: validation, write to the configuration center, read-back comparison.
4. In the publication record confirm that the status is succeeded and that the read-back matches.
5. If the result is unknown, look up the execution result first instead of submitting again.

> **Note** A successful publication only proves the configuration center was updated, not that a process loaded it or a request will be blocked. With a managed envelope the reader also compares binding_id, rule_kind and profile_id; any mismatch raises RuleSetSnapshotInvalid rather than silently decoding with the wrong profile.

## Confirm the loading and the enforcement

This step requires three layers of evidence, each collected on its own.

1. First layer: read back independently from the configuration center and confirm that the content matches what you published.
2. Second layer: look at the instance usage on the rules page and confirm that the target instance shows the rule as loaded.
3. Third layer: send steady traffic above the test limit and observe the rejection responses and the change in the admitted and blocked counters.
4. After the verification, restore the daily version and verify once more.

> **Note** 3 QPS is only an easily observed test value, not a production recommendation. Several rules may match the same request, so decide the block reason from the specific resource and from the snapshot that actually took effect.

## What to do when a step is stuck

The most common sticking points, in process order. Read the signal before acting; do not skip the signal and retry directly.

| Stuck at                                                | Read first                                   | How to handle it                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :------------------------------------------------------ | :------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Saving the draft fails                                  | The error code returned by the command       | The error set is `invalid_request`, `unauthenticated`, `forbidden`, `csrf_failed`, `idempotency_conflict`, `validation_failed`, `rate_limited`, `service_unavailable`. For content problems fix the fields and save again; for `rate_limited` wait until the `retryAfterMs` deadline in the response and submit again.                                                                                                                          |
| Validation reports unsupported fields                   | The `issues` in the validation receipt       | Issue categories are only `validation`, `unsupported_field`, `unsupported_capability`, `unknown_field`, `conflict`, at most 32 per run, and each carries a `path` pointing at the field of the rule. The whole candidate is rejected and never takes effect partially. `sentinel-java-v1`, `sentinel-go-v1` and `sentinel-rust-v1` only support `grade=QPS`, `strategy=DIRECT`, `controlBehavior=REJECT`, `limitApp="default"`.                 |
| The publication result is unknown                       | The publication phase and the receipt status | The phases are `awaiting`, `running`, `succeeded`, `failed`, `unknown`; the receipts are `applied`, `pending`, `failed`, `unknown`, `restart_required`. Look up the execution result with the same idempotency key instead of sending it under a new key. `unknown` must not be counted as success, and `failed` does not mean the write failed either — a read-back mismatch also lands in `failed`, with the reason code `readback_mismatch`. |
| The publication succeeded but the instance did not load | The load observation                         | The load status is `applied`, `failed_keeps_last_known_good`, `failed_before_first_load`, `not_observed`; the freshness is `current`, `stale`, `unknown`. Confirm that the Reporter completed the enrollment and that the `profile_id` reported by the runtime matches the profile on the binding. When `membership_complete` is false the membership list is empty, and the console must show unknown rather than "no rules".                  |
| The instance loaded the rule but does not block         | The resource name and the threshold unit     | The resource name has to match the runtime instrumentation character for character. A QPS threshold is a request count within a one-second window, not a concurrency count and not a number of milliseconds. Also confirm that no other rule matched first — the block reason may be one of `FLOW`, `CIRCUIT_OPEN`, `SYSTEM`, `PARAM_FLOW`, `AUTHORITY`.                                                                                        |

> **Note** Not one of these rows suggests clicking again. Resubmitting the same idempotency key does not produce a second write; only a new key does, and `idempotency_conflict` means exactly that this key already belongs to another operation.
