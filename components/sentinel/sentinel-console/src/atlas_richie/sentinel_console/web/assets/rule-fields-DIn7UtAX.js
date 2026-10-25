const e=`---
title: Rule fields, units and conditional configuration
summary: Check every item against its meaning, so seconds and milliseconds,
  ratios and percentages do not get mixed up.
prerequisite: You know the five rule families; the current binding profile must
  support the target rule family.
outcome: You know the unit, the range and the required condition of every field,
  and how to verify it.
---

## First separate the three layers of field names

The same concept has different names on three layers. Mixing these three layers together is the most common cause of a rejected submission — especially when you follow the Python SDK documentation while filling in the interface form.

| Layer                              | Who uses it                                     | Naming style       | Example                                                  |
| :--------------------------------- | :---------------------------------------------- | :----------------- | :------------------------------------------------------- |
| SDK API layer                      | When you write rules in your application code   | snake_case         | \`threshold\`, \`scope\`, \`control\`, \`stat_interval_ms\`      |
| Console wire layer                 | The fields you fill in in the console interface | camelCase          | \`count\`, \`strategy\`, \`controlBehavior\`, \`statIntervalMs\` |
| Configuration center payload layer | What finally gets written into Nacos / Consul   | Forked per profile | See the table below                                      |

What you fill in on the form is the **second layer**. But the second layer is not the third one — the actual payload that lands in the configuration center is re-encoded according to the binding profile:

| profile            | The field names written into the configuration center                                                                                                          |
| :----------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| sentinel-python-v1 | Reuses the wire layer: \`resource\`, \`count\`, \`controlBehavior\` and so on                                                                                        |
| sentinel-java-v1   | Reuses the wire layer: \`resource\`, \`count\`, \`controlBehavior\` and so on                                                                                        |
| sentinel-rust-v1   | Reuses the wire layer                                                                                                                                          |
| sentinel-go-v1     | Switches to a fixed set of fields: \`resource\`, \`threshold\`, \`statIntervalInMs\`, \`tokenCalculateStrategy\`, \`controlBehavior\`, \`relationStrategy\`, \`refResource\` |

> **Note** So the sentence "you type \`count\` on the form and it is \`count\` in the configuration center" **only holds for Python, Java and Rust**. In the configuration center of the Go profile it is \`threshold\`. Hand-editing a Go rule in the configuration center and copying the field names from the form writes an object the runtime cannot read.

> **Note** The payload of the Go profile is a **fixed set of fields**, not a set that grows and shrinks with the conditions: \`statIntervalInMs\` is always 1000, \`tokenCalculateStrategy\` and \`relationStrategy\` are always 0, and \`refResource\` is always an empty string. That is the output convention of the Go encoder, not a general way of writing "the conditional field with an empty value".

> **Note** The wire layer has one more constraint: an optional field that is enabled by a condition must be omitted entirely when the condition is off; it must not be serialized as null or as an empty string.

### The three names of one field

Take the threshold of flow control as an example; the same meaning is named differently on the three layers:

| Layer              | Field name  | Value               |
| :----------------- | :---------- | :------------------ |
| SDK API layer      | \`threshold\` | The threshold value |
| Console wire layer | \`count\`     | The threshold value |
| Go profile payload | \`threshold\` | The threshold value |

And the concept "which dimension do you limit by":

| Layer              | Field name                                      | Value                             |
| :----------------- | :---------------------------------------------- | :-------------------------------- |
| SDK API layer      | \`scope\`                                         | The limiting dimension            |
| Console wire layer | \`strategy\`                                      | 0 direct / 1 associated / 2 chain |
| Go profile payload | \`tokenCalculateStrategy\` and \`relationStrategy\` | Always 0 (direct match)           |

> **Note** The payload of the Go profile contains two fields that are both 0, \`tokenCalculateStrategy\` and \`relationStrategy\`, plus the empty string of \`refResource\`. They are a direct expression of the subset this profile supports: only QPS limiting with a direct match is supported, so the associated and chain strategies have no corresponding value.

## Flow control fields

Flow control limits a resource by rate, either QPS or concurrency. The meaning of the threshold changes with the threshold type.

| Field             | Unit and value range                                                                                                                 | Required when                             |
| :---------------- | :----------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------- |
| resource          | Non-empty string, at most 512 characters                                                                                             | Required                                  |
| limitApp          | default means the origins are not distinguished                                                                                      | Required                                  |
| grade             | 1 means QPS; 0 means concurrency                                                                                                     | Required                                  |
| count             | With QPS it is the request count in the time window; with concurrency it is the in-flight concurrency. It must be greater than 0     | Required                                  |
| strategy          | 0 direct; 1 associated; 2 chain                                                                                                      | Required                                  |
| controlBehavior   | 0 immediate rejection; 1 warm-up; 2 queueing                                                                                         | Required                                  |
| refResource       | The target resource in associated or chain mode                                                                                      | Required when strategy is not 0           |
| warmUpPeriodSec   | Warm-up period, in seconds                                                                                                           | Required when controlBehavior is warm-up  |
| maxQueueingTimeMs | Maximum queueing wait, in milliseconds                                                                                               | Required when controlBehavior is queueing |
| clusterMode       | The cluster flow control switch                                                                                                      | Omitted when it is off                    |
| clusterConfig     | Threshold type, sample count, window in milliseconds. The window must not be smaller than the sample count and must divide it evenly | Required when cluster mode is on          |

> **Note** In one flow control rule the warm-up period is in seconds while the queueing wait is in milliseconds. Mixing the units is the easiest mistake to make.

## Circuit breaking fields

Circuit breaking protects a downstream dependency. There are three trigger conditions, and the threshold means something different in each of them.

| Field              | Unit and value range                                                                                                                                                          | Required when                       |
| :----------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------- |
| resource           | Non-empty string                                                                                                                                                              | Required                            |
| grade              | 0 slow-call ratio; 1 error ratio; 2 error count                                                                                                                               | Required                            |
| count              | With slow-call ratio it is the response time threshold in milliseconds; with error ratio it is a ratio between 0 and 1; with error count it is a count and must be an integer | Required                            |
| slowRatioThreshold | Slow-call ratio threshold, greater than 0 and at most 1                                                                                                                       | Only needed in slow-call ratio mode |
| timeWindow         | How long the breaker stays open                                                                                                                                               | Required                            |
| minRequestAmount   | The minimum number of requests needed to trigger the breaker, a positive integer                                                                                              | Required                            |
| statIntervalMs     | Statistics window, in milliseconds                                                                                                                                            | Required                            |

> **Note** Do not treat a ratio as milliseconds or as a count, and do not convert back the other way either. Both the slow-call ratio and the error ratio run from 0 to 1, not from 0 to 100.

## Hot parameter fields

Hot parameter rules limit the traffic per parameter value, which requires the runtime to extract the parameter reliably.

| Field             | Unit and value range                                                                | Required when  |
| :---------------- | :---------------------------------------------------------------------------------- | :------------- |
| resource          | Non-empty string                                                                    | Required       |
| grade             | The current page only allows QPS                                                    | Required       |
| count             | Threshold, a positive number                                                        | Required       |
| durationInSec     | Statistics duration, in seconds, a positive integer                                 | Required       |
| paramIdx          | Parameter index, starting at 0                                                      | Required       |
| paramFlowItemList | Exception items: parameter type, exact value, threshold. At most 100 items per rule | May be omitted |

> **Note** The parameter index starts at 0, not 1. Typing an index into the form does nothing on its own — the parameter has to reach the runtime instrumentation, and only then can the runtime extract it.

## System protection fields

System protection uses the overall pressure signal of the runtime to protect the ingress. It has no resource name, because it protects the whole process.

| Field             | Unit and value range                           | Description             |
| :---------------- | :--------------------------------------------- | :---------------------- |
| highestSystemLoad | Overall load threshold                         | Can be disabled with -1 |
| avgRt             | Mean response time, in milliseconds            | Can be disabled with -1 |
| maxThread         | Maximum concurrent threads, must be an integer | Can be disabled with -1 |
| qps               | Ingress QPS                                    | Can be disabled with -1 |
| highestCpuUsage   | CPU usage, a value between 0 and 1             | Can be disabled with -1 |

> **Note** The five thresholds can be disabled one by one, and the disabled value is -1, not 0 — 0 is a valid threshold. At least one of them has to be enabled. CPU runs from 0 to 1; entering 80 would be read as 8000%.

## Authority fields

Authority rules decide between allow and block based on the caller origin that the runtime resolves.

| Field    | Unit and value range                                                                            | Required when |
| :------- | :---------------------------------------------------------------------------------------------- | :------------ |
| resource | Non-empty string                                                                                | Required      |
| strategy | 0 allowlist; 1 blocklist                                                                        | Required      |
| limitApp | A list of origins separated by commas. Each entry must be non-empty, and duplicates are removed | Required      |

> **Note** The runtime has to resolve the origin reliably. Do not treat an arbitrary string from the client as a trusted identity.

## Unit traps at a glance

The table below collects the mistakes the documentation calls out. Go through it before publishing.

| Field                                  | Correct unit or value        | Common mistake                   |
| :------------------------------------- | :--------------------------- | :------------------------------- |
| highestCpuUsage                        | A ratio between 0 and 1      | Entering 80 to mean 80%          |
| A disabled system protection threshold | -1                           | Entering 0                       |
| slowRatioThreshold                     | Greater than 0 and at most 1 | Entering 50 to mean 50%          |
| count in error ratio mode              | Between 0 and 1              | Entering anything other than 0.5 |
| warmUpPeriodSec                        | Seconds                      | Entering milliseconds            |
| maxQueueingTimeMs                      | Milliseconds                 | Entering seconds                 |
| statIntervalMs                         | Milliseconds                 | Entering seconds                 |
| durationInSec                          | Seconds                      | Entering milliseconds            |
| paramIdx                               | Starts at 0                  | Starting at 1                    |
| The circuit breaking timeWindow        | See the note below           | Assuming seconds from memory     |

> **Note** The unit of the circuit breaking timeWindow is not stated explicitly in the rule documentation. In the known shipping implementations the Nacos codec handles it as milliseconds, but the documentation gives no authoritative definition; go by the encoder implementation you actually deployed, and do not assume the Java convention.

## When a conditional field must be omitted

An optional field that is enabled by a condition must be omitted entirely when the condition is off. It must not be serialized as null, as an empty string or as 0 — writing it declares that the condition is on.

Field names the wire layer does not know are not silently dropped either. Validation records them as \`unknown_field\` or \`unsupported_field\` and rejects the whole candidate. Prefer a full rejection over a configuration that looks effective while the runtime interprets it its own way.

Omitting differs from writing null because the runtime enables a capability based on whether the field is present. A present field can bring an empty rule set along, while an absent field means "this one does not apply".

1. Before opening the rule workbench, confirm the profile on the binding and fill in the field subset it supports.
2. After filling in, check every conditional field: if the condition is off, delete the whole field and leave no null, no empty string and no 0.
3. Check the units one by one: do not copy seconds into milliseconds or the other way round, make sure the ratios land between 0 and 1, and make sure the parameter indexes start at 0.
4. Run the validation right after saving and fix each entry by the \`path\` in \`issues\`. The validation returns a \`validationId\` and a \`candidateChecksum\`; after the version is frozen, \`checksum\` must equal \`candidateChecksum\`.

| Field               | Enablement condition                      | How to write it when the condition is off           |
| :------------------ | :---------------------------------------- | :-------------------------------------------------- |
| \`refResource\`       | \`strategy\` is not 0 (associated or chain) | Omit it entirely when \`strategy\` is 0               |
| \`warmUpPeriodSec\`   | \`controlBehavior\` is warm-up              | Omit it entirely when it is not warm-up             |
| \`maxQueueingTimeMs\` | \`controlBehavior\` is queueing             | Omit it entirely when it is not queueing            |
| \`clusterConfig\`     | Cluster mode is on                        | Omit it entirely when \`clusterMode\` is off          |
| \`paramFlowItemList\` | May be omitted                            | Omit it entirely when no exception items are needed |

> **Note** "Omit" and "enter 0" are not the same thing. The five system protection thresholds can be disabled one by one with -1, because 0 is a valid threshold; that is a rule of system protection itself and not the same mechanism as the conditionally optional fields.
`;export{e as default};
