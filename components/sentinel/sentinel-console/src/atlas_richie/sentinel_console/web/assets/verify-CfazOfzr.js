const e=`---
title: "How to confirm the integration succeeded: three layers of verification"
summary: Read it, loaded it, really blocked it — three separate things to verify.
prerequisite: You have registered a source and a rule binding, and you have a
  test service that can send requests.
outcome: For every integration, produce three independent layers of evidence
  instead of only seeing 'the Rules page has rules'.
---

## Why it has to be three layers

Seeing rules in the configuration center only proves that the text exists. It does not prove that a process loaded it, nor that requests are being rejected. These three layers have their own failure causes and their own observation points.

| Layer      | What it verifies                                         | Observation point                                            | Usual failure cause                                                    |
| :--------- | :------------------------------------------------------- | :----------------------------------------------------------- | :--------------------------------------------------------------------- |
| 1. Read    | The content in the configuration center parses correctly | The read status and the rule count in the rule catalog       | Wrong configuration location, wrong credentials, profile mismatch      |
| 2. Load    | A process accepted this snapshot                         | The instance load state, the member fingerprints             | Unsupported profile, identity not enrolled, the process just restarted |
| 3. Enforce | The rate limiter really works at runtime                 | The rejection responses and the metrics of business requests | Resource name mismatch, wrong threshold unit, wrong window             |

## Layer one: reading the rules

Read on the console side first. In the rule catalog, click read from the configuration center and look at the rule count and the read status.

1. Select the binding on the Rules page and click read from the configuration center.
2. Confirm that the status is 'current snapshot', not 'stale snapshot' or 'not yet read'.
3. Confirm that the rule count is not zero. If it is zero, confirm that the location exists and the rule array is empty, rather than the read having failed.
4. On the business process side, confirm that the same content is parsed correctly. Both the Java and the Go demo expose this through /rules.

\`\`\`bash

curl -s http://127.0.0.1:18081/rules
\`\`\`

> **Note** The /rules output of Java and Go is plain-text key/value lines (rules_loaded, rule_count and so on), while the Rust demo returns JSON. If you cannot see rules_loaded=true, the process has not obtained a valid snapshot yet.

## Layer two: instance loading

This layer looks at the load observations reported by the runtime, not at the content in the configuration center. The instance usage on the Rules page comes from here.

1. Confirm that the application has an enrolled Reporter. When the expected instance count is unknown the interface shows unknown rather than zero.
2. Expand the instance usage on the Rules page and see whether any instance confirms a load.
3. If it shows unknown, check whether the member manifest is complete, whether the profile matches, and whether the observation is stale.
4. After a process restarts, the old load receipt no longer applies; wait for a new observation.

> **Note** When the member manifest is incomplete, the negotiation has not happened, or an observation is missing, the interface must show unknown. Treating unknown as 'not loaded' leads to exactly the opposite conclusion.

## Layer three: it really blocked

Only the actual response of a business request proves the third layer. A threshold well below the production capacity makes the effect easiest to observe.

1. First confirm with no requests that /rules is loaded.
2. Send steady traffic above the threshold and watch for rejection responses.
3. Record the response sequence. In the real provider acceptance record, a threshold of 3 gives 200, 200, 200, 429, 429 over five consecutive requests.
4. Return to the console and confirm that blocked counts appear in Overview and a request block rate curve appears in Realtime.

\`\`\`bash

for i in $(seq 1 5); do curl -s -o /dev/null -w "%{http_code}\\n" http://127.0.0.1:18081/api/hello; done
\`\`\`

> **Note** 3 QPS is a test value chosen for easy observation, not a production recommendation. Several rules may match the same request at once, so the block reason has to be judged against the specific resource and the snapshot actually in effect.

## How long a rule change takes to take effect

Rule content is pulled by polling, not pushed. All three demos poll once per second.

| Stage                                    | Typical latency            | Owner                 |
| :--------------------------------------- | :------------------------- | :-------------------- |
| The configuration center content changes | Immediately                | Configuration center  |
| The process pulls the new content        | Up to about 1 second       | Runtime polling       |
| The load observation is reported         | One more reporting period  | Reporter              |
| The console shows it loaded              | One more collection period | Collector and console |

> **Note** When you see 'the Rules page still shows the old content', wait one round before you judge. Rushing to change the content in the configuration center can leave it in a mess.

## Four common misjudgments

The purpose of the three layers is to separate 'read', 'loaded' and 'enforced'. All four misjudgments below happen between these layers, and they share one trait: using one layer's evidence to answer another layer's question.

| Misjudgment                                                                   | Why it is wrong                                                                                                                                                                   | The evidence to use                                                                                                                                                                                                                |
| :---------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The configuration center read the rules, so the rules are in effect           | Reading only proves that the content parses; it does not prove that any process accepted it                                                                                       | Look at the instance load observation: a complete member manifest, a matching member fingerprint for that rule, and a fresh observation                                                                                            |
| The load observation has a value, so that is what is in effect                | A load observation carries four independent values: the source revision, the source byte digest, the canonical snapshot digest and the member digest                              | Compare the source revision and the member fingerprints one by one; a change in one does not imply that the others changed                                                                                                         |
| One request was blocked, so every instance blocks                             | Blocking happens inside a single process; when the instance manifest is incomplete the interface shows unknown, which does not mean that the other instances are in effect either | Confirm them one by one in the instance usage, or send a set of above-threshold requests to each instance separately                                                                                                               |
| The publication endpoint returned 202, so the rules are written and in effect | 202 only means that the server accepted this one idempotent operation; it does not mean that the provider has written it or that instances have loaded it                         | Check the publication receipt status (applied / pending / failed / unknown / restart_required), then wait for the instance load observation to confirm; failed does not mean the provider write failed, and unknown is not success |

> **Note** The common consequence of these four misjudgments is declaring success too early. Declaring success too early costs far more than declaring it a little late: being a little late costs at most one more polling round, while being early lets an ineffective change be treated as protection that is already live.
`;export{e as default};
