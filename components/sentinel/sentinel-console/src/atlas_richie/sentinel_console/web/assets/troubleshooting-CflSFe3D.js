const e=`---
title: Troubleshooting common problems
summary: Locate the problem by symptom, without repeated submissions and
  repeated resets.
prerequisite: Access to the relevant page; management actions need an admin account.
outcome: You can locate empty charts, rules that do not take effect, read
  failures and recovery problems.
---

## Start from the symptom

Find the symptom you see in the left column, then check in the order of the middle column.

| Symptom                              | Check first                                                               | Common causes                                                                                        |
| :----------------------------------- | :------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------------- |
| The rules are not visible            | The binding catalog, the source connection, the profile                   | Wrong configuration location, wrong credentials, mismatched profile                                  |
| The rules are there but do not block | The resource name, the window threshold, the version actually loaded      | The resource name differs from the instrumentation, the unit is wrong, an old version is deployed    |
| The application metrics are empty    | Enrollment, mTLS, protocol negotiation, completed responses and histogram | The certificate is not registered, the identity does not match, only part of the fields was reported |
| The host metrics are empty           | The scrape target, the label mapping, the profile, the time range         | The target is not up, the labels do not line up, the profile does not match                          |
| The incident list is empty           | Whether the event source is connected                                     | The event path was never connected; it does not mean there was no fault                              |
| The publication result is unknown    | The execution result query                                                | Do not resubmit; query the result first                                                              |

## The rules are not visible

Check in this order; each step rules out one class of causes.

1. In the rule binding catalog, confirm that the binding exists and that the environment and the application identifiers are correct.
2. On the Connections and collection tab, confirm that the source probe is usable.
3. Read the configuration center and check whether the read state is "current snapshot", "stale snapshot" or "not yet read".
4. Check the configuration location: Nacos uses the namespace ID, the group and the Data ID; Consul uses the datacenter and the full KV key.
5. Confirm that the business process reads the same location. The console and the business process pointing at different locations is the most common cause.

## The rules are there but do not block

Configuration existing only means the text is there. Blocking requires that the rule is loaded, that it matches, and that the threshold is computed correctly.

1. Check that the resource name matches the instrumentation character for character, including the case, the spaces and the path.
2. Check the threshold unit: QPS is counted within a one-second window, and swapping seconds with milliseconds is the most common mistake.
3. On the rules page, confirm which snapshot the instance actually loaded, rather than the one you think it loaded.
4. Confirm that no other rule matched first and blocked the same request.
5. Test with steady traffic above the threshold; a small number of requests over a short period may simply not exceed it.

> **Note** The Java and Go adapters reject the whole candidate snapshot during validation. One unsupported field and not a single rule takes effect. When investigating "all the rules suddenly stopped taking effect", look at the content of the most recent publication first.

## The metrics are empty

Empty metrics have several different causes, and each of them needs a different response.

1. Confirm that the Reporter has been enrolled and that the certificate fingerprint matches the runtime.
2. Confirm that the mTLS connection was really established and did not fall back to plaintext.
3. Confirm that the protocol negotiation succeeded: a profile name in the configuration does not mean the negotiation succeeded.
4. Confirm that the report body contains both the completed request count and the histogram — with counters alone you cannot compute the RT.
5. Confirm that the path from the collection side to the console is up.

## A write operation returns an unknown result

A browser timeout does not prove that the write failed. The server may have finished writing; only the receipt did not come back.

1. Query the result of this request with the operation query interface first.
2. Decide whether to retry only after confirming the result.
3. If you retry, use the same idempotency key — a new key is treated as a new operation and produces a second write.
4. If the result really is in an unknown state, keep it in that state and go and check the underlying facts instead of probing with another click.

> **Note** When the operation query returns "not found", that does not mean the operation did not happen, and it does not authorize you to replay it under a new key.

## When to stop

The value of troubleshooting is elimination, not trial and error. When you see the signals below, stop and check the facts before deciding what to do next.

When two numbers on the same page do not agree, or the same resource yields different conclusions in two places, stop operating. Different metric definitions (\`completed_http_requests\` versus \`attempted_entries\`), different time window boundaries (the Console uses the UTC half-open interval \`[from,to)\`) and different sampling coverage can all make the same batch of requests show up as different numbers in two places. First confirm which observation point, which time window and which definition every number comes from.

Do not resubmit a write operation whose result is unknown. A different idempotency key produces a second write; querying with the same key is safe. A query result of "not found" does not mean the operation never happened.

When the content in the configuration center is not what you expected, compare the two side by side first: the version, the source revision, the byte digest and the canonical digest recorded by the console against the content that was actually read. If the digests do not match, one side is not looking at the same snapshot. Do not change either side before the comparison is clear.

The following belong to the platform maintainers, and retrying in the interface only amplifies the impact: generating, distributing and rotating the encryption material and the certificates; inconsistent decisions between the cross-language protocol implementations; runtime crashes or processes that restart repeatedly; and the same rule input producing different conclusions in the adapters of different languages.

> **Note** Stopping is not giving up. Write down the facts you have confirmed — the time, the scope, the observation point, the exact values — and then go and find someone. With the facts complete, the problem usually classifies itself.
`;export{e as default};
