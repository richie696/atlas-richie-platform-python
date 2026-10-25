---
title: Frequently asked questions
summary: The questions that come up most often.
prerequisite: No prior knowledge needed.
outcome: Confirm a common doubt quickly, without reading the whole document.
---

## About the console

These are the questions people ask most often about the console itself.

| Question                                                                        | Answer                                                                                                                                                                             |
| :------------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What does "interaction design prototype" in the top right of the page mean?     | This is demo mode: metrics, applications, rules and connection status are sample data, and nothing reaches production services or the configuration center                         |
| Can I read the documentation without logging in?                                | Yes. The documentation center is public static content, and it stays readable when the console is not initialized, when you are not logged in, or when a dependency is unavailable |
| Why is there no initialization entry on the login page?                         | Initialization is a one-time procedure; once it has finished the server closes the window, and the login page no longer offers a way to initialize again                           |
| Can I call the interfaces directly to bypass the restrictions in the interface? | No. Hiding something in the interface is a matter of experience; the server re-evaluates the role on every request                                                                 |
| Does switching the language lose the current article?                           | No. Articles have stable identifiers, and switching the language keeps you on the same one                                                                                         |

## About rules

These are the questions people ask most often about rules themselves.

| Question                                                                    | Answer                                                                                                                                                                             |
| :-------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Why was my publication rejected when I set warm-up or cluster flow control? | The current Java, Go and Rust profiles only support the one-second QPS direct-rejection subset of flow control. The other capabilities are explicitly rejected rather than ignored |
| Does saving a draft affect production?                                      | No. Saving a draft writes only to the Console database, not to the configuration center                                                                                            |
| I published, but nothing changed in production                              | Publishing only updates the configuration center. An instance loads it at the next poll, at most about a second later                                                              |
| Does the version number get smaller after a rollback?                       | No. A rollback is a new publication, and the version number keeps moving forward; only the content goes back to the historical one                                                 |
| The rule array is empty — does that mean there are no rules?                | Yes, an empty array explicitly means that the position exists and holds no rules. That is different from "cannot be read"                                                          |
| Can I push a whole rule set into the configuration center by hand?          | Yes, but the entire snapshot has to match the field subset of the profile; otherwise the adapter rejects the whole snapshot instead of applying part of it                         |

## About integration

These are the questions people ask most often when integrating a service.

| Question                                                   | Answer                                                                                                        |
| :--------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------ |
| Can the Java and the Go configuration settings be swapped? | No. NACOS_SERVER_ADDR in Java includes the port, while Go splits it into two variables, host and port         |
| Can I use the Java certificate with Go directly?           | No. Java uses PKCS#12 while Go and Rust use PEM, and the variable names differ as well                        |
| Can I use the Java rule JSON with Go directly?             | No. The threshold field in Go is called threshold rather than count, and the window field is statIntervalInMs |
| Do the three demos return the same /rules format?          | No. Java and Go return plain-text key-value lines, while Rust returns JSON                                    |
| Do I have to give the private key to the console?          | No. A private key is never sent to the console or to the Collector; register the certificate fingerprint only |
| Can I use a token instead of mTLS?                         | No. mTLS is the only source of the Reporter's identity                                                        |

## About metrics

These are the questions people ask most often about the metric definitions.

| Question                                                         | Answer                                                                                                                                           |
| :--------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| An empty curve means there was no traffic, right?                | Not necessarily. Empty means there were no valid samples in that period, and the collection path may be broken as well. Missing data is not zero |
| Can mean RT replace RT p95?                                      | No. They answer different questions, and without a histogram you should not draw a p95 at all                                                    |
| Can I use the host CPU curve as the process CPU?                 | No. The collection scope differs, and the container scope is a third scope again                                                                 |
| Will there be a business TPS without instrumentation?            | No. TPS comes only from explicit business instrumentation and is never derived from QPS                                                          |
| What shows when the denominator of the request block rate is 0?  | Unavailable. It never shows zero and never infers a ratio                                                                                        |
| Is the p95 across instances the average of the per-instance p95? | No. Merge the bucket counts first, then take the quantile of the merged histogram                                                                |

## More questions

These are common questions that span the topics.

1. First confirm which mode you are in, then confirm the identity and the permissions: the only roles are `admin` and `view`, and only `admin` can change the rules.
2. Confirm the scope of this action: saving a draft, freezing a version and publishing are three different things, and only publishing writes content into the configuration center.
3. Confirm that the evidence chain is closed: the publication receipt, the load observation and an actual rejection response — you need all three.
4. When any layer does not line up, stop and check the facts instead of probing with repeated operations.

| Question                                                                      | Answer                                                                                                                                                                                                                                                                                                                                                           |
| :---------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Is the console in demo mode or a real environment?                            | It is demo mode when the top right of the page shows "interaction design prototype" or the login page shows "local demo mode": metrics, applications, rules and connection status are simulated and do not reach production services or the configuration center. The demo login names are `admin` and `viewer`, while the role ids are only `admin` and `view`. |
| Do these documents cover every capability?                                    | No. The documentation only covers what has been frozen and can be verified. A declared interface contract does not mean that the real integration or the end-to-end acceptance has passed. Where the documentation gives no single definition, follow your actual implementation.                                                                                |
| Can I edit rule content by hand?                                              | Yes, but the whole snapshot has to match the field subset of the binding profile. The adapter rejects the whole snapshot; it does not apply part of it, and it does not silently drop the fields it does not know before writing it back.                                                                                                                        |
| Can I change several rules at once?                                           | Yes. A version holds at most 1000 rule records, and one candidate validation reports at most 32 issues. Publishing replaces the whole content, so what is written is the entire content of that version.                                                                                                                                                         |
| Is publishing incremental?                                                    | No. Publishing replaces the whole content, and the position is fully overwritten by this version. To keep the old rules you must include them in the new version before publishing.                                                                                                                                                                              |
| Can I change the rules that are currently in effect?                          | No. The content in effect lives in the configuration center, not in the Console draft. To change it you have to create a draft, validate it, freeze a new version and publish it.                                                                                                                                                                                |
| Which is more authoritative, the load observation or the publication receipt? | Each answers a different question. The publication receipt says "what was written", the load observation says "what the process actually loaded". To prove that requests were really blocked you also need an actual rejection response.                                                                                                                         |
| Can the metrics predict capacity?                                             | No. Metrics are after-the-fact observation, not a capacity model. Thresholds come from a load test baseline and the SLO, and the metrics only verify the effect of an adjustment.                                                                                                                                                                                |
| Can the host associations be inferred automatically?                          | No. Host associations are registered explicitly and are never inferred from the scrape labels.                                                                                                                                                                                                                                                                   |
| Can the Console run several replicas across hosts?                            | Not under the current contract. `SENTINEL_CONSOLE_WORKERS` is the number of Uvicorn worker processes on the same host, `1` by default; multiple workers are only supported when they share the same local deployment state path and the same SQL database. NFS and multi-host replicas are out of scope.                                                         |
| Can the membership list in a load observation serve as proof of completeness? | No. When `membership_complete` is false the membership list is empty, and the console must show unknown rather than "no rules".                                                                                                                                                                                                                                  |
| Does a 202 response mean the write succeeded?                                 | No. A 202 only means that the server accepted that one idempotent operation. Look at the phase state after the three phases have run, and at whether the receipt is `applied`, `pending`, `failed`, `unknown` or `restart_required`.                                                                                                                             |
