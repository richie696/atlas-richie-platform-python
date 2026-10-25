const e=`---
title: Drafts, versions, event plans and rollback
summary: Keep a version for the event, then restore the daily rules afterwards.
prerequisite: The first rule has already been verified; an admin account.
outcome: Tell saving, publishing and restoring apart, and confirm that the
  result really took effect.
---

## Three different things

These three words get mixed up easily, but their effects are completely different.

| Action           | What it changes                                      | Does it affect a running service                       |
| :--------------- | :--------------------------------------------------- | :----------------------------------------------------- |
| Save a draft     | Editable content in the Console database             | No. A draft does not write to the configuration center |
| Freeze a version | Produces an immutable snapshot                       | No. The version is only recorded                       |
| Publish          | Writes a whole version into the configuration center | Yes. The instances load it after the next poll         |

## Daily -> event -> daily

The typical scenario is temporarily relaxing a resource during a promotion and restoring it afterwards. This is the full procedure.

1. Create a draft from the confirmed daily rules and note the daily version identifier.
2. Validate the capacity and the compatibility for the event window and confirm that the new threshold will not overwhelm the downstream.
3. Save it as a separate version whose name states the event window.
4. Review the diff and confirm that only the intended rules changed.
5. Publish this version and record the operator, the time window, the target binding and the rollback version.
6. After the event ends, publish the daily version again as a new draft.
7. Read the configuration center back once more and check the instance load status.

> **Note** Restoring the daily rules also produces a new publication. Only switching the selected version on the page does not change what the runtime is using.

## A rollback is a new publication too

A rollback is not changing the version number back; it is selecting historical content, taking the current configuration as the baseline and starting a new publication. So it needs an idempotency key as well, it leaves a publication record as well, and it appears in the audit trail as well.

Version numbers never go backwards. After a rollback you have a newer version number whose content is the older one.

> **Note** Even when the content is exactly the same, a repeated publication and a rollback must be tied to a new publication identity; otherwise the audit chain breaks.

## Event plans and their outcomes

An event plan records when to switch to which version and when to restore, and the backend executes it on schedule.

A plan has several states: pending, enabling, event version enabled, restoring, restore confirmed, conflict or execution blocked, and cancelled follow-up plans.

1. When creating a plan, pick the target version and the restore version explicitly.
2. Fill in the start and end times with the time zone. A recurring time must be chosen explicitly, and a missing time makes the plan invalid.
3. Before saving, check whether an overlapping plan exists.
4. After saving, refresh the backend facts and confirm the plan status.
5. When the time comes, confirm that the event version is enabled; after it ends, confirm the restore.

> **Note** A triggered plan does not mean that every instance has taken effect, and it does not mean that every request was handled under the new rule. To confirm the real effect, go back to the load observation.

## What the version catalog contains

Every entry in the version catalog is an immutable snapshot. The fields below say what it records and what does not live on a version.

| Entry                                        | Meaning                                           | Note                                                                                                                                                                                                                                      |
| :------------------------------------------- | :------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Version identifier \`id\`                      | A version identifier, unique within a binding     | After a rollback you get a new identifier; the old one stays in the catalog                                                                                                                                                               |
| \`name\` and \`note\`                            | The version name and the version note             | The name is at most 200 UTF-16 code units, the note at most 2000                                                                                                                                                                          |
| \`createdAt\`                                  | The creation time, UTC with millisecond precision | The stored value is UTC. Convert it for display; do not rewrite what was stored                                                                                                                                                           |
| \`createdById\`                                | The creator                                       | An account identifier, not a display name                                                                                                                                                                                                 |
| \`baseVersionId\`                              | The baseline version                              | It is the anchor for "which version this changed relative to"                                                                                                                                                                             |
| \`checksum\`                                   | The digest of the version content                 | It changes when the content changes. It is the same value as \`candidateChecksum\` in the validation receipt                                                                                                                                |
| \`records\`                                    | The rule records inside the version               | At most 1000 rule records per version                                                                                                                                                                                                     |
| \`kind\` and \`profile\`                         | The rule family and the profile on the binding    | They decide where this version can be published                                                                                                                                                                                           |
| Validation identifier and candidate checksum | \`validationId\` and \`candidateChecksum\`            | The validation is a read-only evaluation; after it passes, the version is frozen with \`validationId\`. A candidate checksum that does not match the frozen checksum is rejected, so a version whose content does not match is never frozen |
| Activation window                            | Not on the version                                | Recorded by the event plan: target version, restore version, start and end times with time zone, recurring time                                                                                                                           |
| Publication target                           | Not on the version                                | Decided by the publication record and by the target on the binding. Nacos: namespace, group, Data ID; Consul: datacenter and the full KV key                                                                                              |

> **Note** Versions cannot be modified. To adjust one you have to create a draft based on it, validate it and freeze a new version. Each binding keeps at most 1000 versions. To see what a version changed relative to another, locate the baseline with \`baseVersionId\` and compare the rule records one by one; do not guess from the version names.

## Managed publications: align the target before reading

The Console backend writes Managed Rule Publication Envelope V1 to the binding's exact configuration location. The browser submits only Console API commands and never accesses Nacos / Consul directly. The Runtime reads the envelope through an explicitly enabled metadata-aware source adapter.

The read path validates the production contract, then checks binding_id, rule_kind and profile_id against the target binding. Any mismatch raises RuleSetSnapshotInvalid and rejects the entire candidate; the envelope cannot change the target binding's decoder by naming another profile.

1. Before publishing, check the source and exact target: Nacos namespace / group / dataId, or the full Consul key; datacenter comes from the registered source. Then check the binding's rule kind and profile.
2. After publishing, confirm independent read-back in the Console. If a managed snapshot is rejected, check whether another binding's envelope was copied to this location; compare binding_id, rule_kind and profile_id one by one. Do not remove metadata or rewrite identities to bypass validation.
3. Correct the binding or publication target and republish through the Console. Check read-back, the Runtime publication receipt, load observation and real business requests separately.

> **Note** Reporting V1 (atlas-richie.reporting/v1) is a Reporter → Collector reporting wrapper, not rule content to paste into a configuration center. A managed rule envelope is not a Reporting V1 report either.
`;export{e as default};
