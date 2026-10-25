const e=`---
title: "Start here: what the console does"
summary: Learn the feature landscape first, then complete one minimal end-to-end loop.
prerequisite: No prior knowledge. Both administrators and viewers can read this end to end.
outcome: Know what problem each page solves, and how to tell that an integration
  really succeeded.
---

## What the console does for you

Sentinel has three parts: the rule content stored in the configuration center, the rate limiter running inside your business process, and the control plane that holds the two side by side. The console is the third one — it reads the configuration center, writes to it, records drafts and versions, and shows which rule version each business process actually loaded.

It does not implement rate limiting for you. The real blocking happens in your business process; the console exists so that you can answer three questions: what the configuration holds right now, which instances have loaded it, and whether requests are actually being rejected.

1. Open the console URL. Before initialization it enters the first-run setup wizard automatically; after initialization it opens the login page.
2. Log in with the administrator account created during initialization; you land on the account maintenance page.
3. Enter Overview from the left navigation and look at overall traffic, latency, blocking and resource pressure.
4. Open the Rules page and register a rule binding, then read the rules that already exist in the configuration center.
5. Connect a test service and send requests, then return to Realtime and the Rules page to confirm the loading and the blocking.

## Six workspaces, one job each

The console's main navigation is arranged by work stage. The table below indexes every later article: when you do not know where to look, find the matching page in the table.

| Page                       | Question it answers                                                                                                        | Required permission                                                 |
| :------------------------- | :------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------ |
| Overview                   | Which applications need attention, and whether behavior and protection stay in sync                                        | View metrics                                                        |
| Applications and instances | Which instance and which collection layer the problem sits in                                                              | View metrics                                                        |
| Rules                      | Where the configuration comes from, who it affects, how to change it safely and confirm it took effect                     | View metrics; write operations also need the write-rules capability |
| Realtime                   | How traffic, response time, blocking and resource pressure move together on one timeline                                   | View metrics                                                        |
| Fault analysis             | What happened first, and which next step the evidence supports                                                             | View metrics                                                        |
| System management          | How to connect the configuration center and host monitoring, and confirm the collection, reporting and authorization chain | Administrator                                                       |
| Documentation              | This page                                                                                                                  | Public, no login required                                           |

## The shortest path through your first operation

The five steps below form one complete minimal loop. Every later article expands on one of them: run this line first, then go deeper as needed.

1. Register a configuration source (Nacos or Consul) in System management and test the connection.
2. On the Rules page, register a rule binding for that source, specifying the environment, application, rule family and configuration location.
3. In the rule catalog, click read from the configuration center and confirm that content comes back — an empty array and a failed read are not the same thing.
4. Point the test service at the same configuration location to read rules, and configure the Reporter to report load observations and metrics.
5. Send traffic above the threshold, confirm that the response is rejected, then return to the console to confirm the instance load state and the metrics.

> **Note** This manual ships with the console source. Every threshold, command and URL here is a teaching example, not a production tuning recommendation; rules and protocols follow the profile you actually bind, the actual negotiation result and your deployment configuration.

## What order to read in

The left catalog is grouped by learning stage, so start at 'Understand the console' and work down. If you already run an environment, the question you will hear most often is 'the rules show up but they do not take effect' — jump straight to 'Connect services → How to confirm the integration succeeded' and 'Manage rules → Create and validate your first flow rule'.

The search box matches titles, summaries, body text, steps, notes and code samples. A specific term finds more than a broad one — search METRICS_COLLECTOR_URL rather than configuration.

## What the console does not do

The console puts configuration, runtime facts and observability data on one table, but it does not make decisions for your business process. The table below lists what the console explicitly does not do, and what happens when it is not done.

Read the table in reverse: the console answers 'what is the state right now', not 'what should it be changed to'. Where a judgement is needed, the evidence comes from load tests, runtime reporting and real requests, and the conclusion belongs to the deployment side.

| What looks like the console's job                              | Where it actually happens                                                                                                                    | What happens without it                                                                                    |
| :------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------- |
| Execute rate limiting and blocking                             | Blocking happens inside the Sentinel rate limiter in the business process; the console only writes configuration and shows the result        | However correct the rule is, if the business process never loads it, not a single request will be rejected |
| Scan servers and list the available environments and instances | Environments and instances come from registration, bindings and the authorized observation catalog                                           | Environments that were never registered appear in no dropdown; register them first                         |
| Conclude what threshold this service should get                | Thresholds come from load tests and capacity baselines; the console only provides the observability data used to derive a baseline           | Reusing a threshold from another specification usually breaks normal traffic on your own machines          |
| Adjust rules automatically after seeing a fault event          | Fault analysis only presents events and evidence; it makes no root-cause assertion and does not change configuration for the deployment side | Automatic rule changes turn one false alarm straight into a production incident                            |
| Guarantee that 'rules on the page means it is live'            | Reading rules, instance load observations and requests actually being rejected are three independent facts, each verified on its own         | Treating 'the configuration exists' as 'it is already in effect' is the most common source of misjudgment  |
`;export{e as default};
