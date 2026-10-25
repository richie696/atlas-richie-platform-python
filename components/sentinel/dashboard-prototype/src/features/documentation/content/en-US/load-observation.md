---
title: The rule is listed, but instance usage is 0 / unknown
summary: The configuration catalog and the runtime loading come from different facts.
prerequisite: The rule binding is registered; you understand what Reporter enrollment means.
outcome: You can tell no instances, not observed, an old version and unknown
  compatibility apart, and know what to do for each.
---

## Three different zeros

"0 instances in use" can mean several completely different things, and each of them needs a different response.

| Displayed                                  | What it really means                                                 | What to do                                                                         |
| :----------------------------------------- | :------------------------------------------------------------------- | :--------------------------------------------------------------------------------- |
| 0 instances (the registered list is empty) | The authoritative list confirms that there is no registered instance | Connect a Reporter and complete the enrollment first                               |
| Unknown                                    | The list or the observation coverage is incomplete                   | Wait for the observations to complete, or check whether the enrollment was revoked |
| 0 loads                                    | The list is complete, but this snapshot does not contain the rule    | Check whether the rule is in the current snapshot                                  |
| Stale                                      | The observation exists but is old                                    | Check whether the process restarted, and report again                              |

> **Note** "Not observed yet" and "confirmed absent" are two different things. When the list is unknown the console must show unknown, never a definite zero.

## Only a complete membership list proves a rule was loaded

A load observation carries a membership list: which rules this snapshot actually contains. Only a complete list that matches the rule you are asking about proves that it was loaded.

The observation actually holds four independent values that cannot substitute for each other: the source revision, the source byte digest, the canonical snapshot digest and the membership digest. Seeing one of them change does not let you infer that another changed too.

1. First check whether the membership list is complete.
2. Then check whether the member fingerprint of that rule matches.
3. Finally check how fresh this observation is.
4. Only when all three hold can you say "this instance loaded a snapshot that contains that rule".

## Troubleshoot in this order

Use this order when the rule clearly exists but the instance shows it as not loaded.

1. Check the source location: is the location bound in the console the same one the business process actually reads?
2. Check the profile on the binding against the profile the process actually negotiated.
3. Check the certificate identity: has the Reporter been enrolled, and does the process start identifier still match?
4. Check the last Collector receipt time to see whether the reporting path is up.
5. For a managed publication, also check the binding identifier, the publication identifier and the target version identifier.
6. For native rules, look at the load observation instead — native rules do not produce publication identifiers, so do not go looking for a publication record that does not exist.

> **Note** Native rules use load observations and never carry a fabricated publication ID. You will not find a publication ID on a native rule page, and that is not a bug.

## Stale and unknown are not the same

Stale means the observation is old but was once valid. Unknown means the information was never fully established in the first place.

A stale observation shows as stale, and you cannot infer from it that the rule was not loaded — the process may simply have stopped reporting. The right action is to find out why the reporting stopped.

## Instance identity and process epochs

"Instance usage is 0 / unknown" is hard to judge because an instance identifier hides another layer: the process epoch. The identity recorded at enrollment has four parts: environment, application, instance, process. The first two decide which application the data belongs to, the third decides which instance, and the fourth decides which process.

A process restart produces a new epoch identifier. Until the same instance identifier reports for the first time in the new epoch, the load observation of the old epoch still exists — but it answers the previous process's question.

1. First confirm that the four-part enrollment identity is complete: environment, application, instance, process. If any part is missing, that process's data will not be attributed to the instance you are looking at.
2. After a process restart, look in the instance list for entries whose epoch identifier has changed. The old epoch does not disappear; it moves into the history with its own status: superseded means it was replaced by a new epoch, revoked means the enrollment was revoked, no_current_epoch means there is no active epoch right now.
3. The events of an old epoch are shown separately and do not count towards the current rule usage. Using the observation of an old epoch to answer "which version is in effect now" produces an expired conclusion.
4. After the process changed, refresh the directory and explicitly select the current process. Earlier load receipts and publication receipts no longer apply to the new epoch, so confirm them again.
5. Host associations carry a process identity as well: environment, host, application, instance, process, plus the revision of the association itself. When the process changes the association must be confirmed again; do not carry over the conclusion from the last session.

> **Note** The interface states it explicitly when it detects a process change: refresh the directory and explicitly select the current process, because the old load receipt no longer applies. That message and the steps above describe the same thing; when it appears, follow it instead of reading stale entries.
