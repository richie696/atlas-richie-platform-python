const e=`---
title: "Rules page: the four stages from reading to changing"
summary: The rule catalog, the instance effective status, the binding management
  and the rule maintenance, stage by stage, for every panel.
prerequisite: You have already registered at least one rule configuration center
  and know which resource you want to protect.
outcome: You know at which stage to look at the current state, at which stage to
  make a change, and which steps a single change goes through.
---

![The rule catalog view of the Rules page: at the top are the four tabs — rule catalog, instance effective status, binding management and rule maintenance; inside the panel are the deployment environment and application filters, the search box and the five Sentinel rule family cards, and at the bottom is the configuration center rule catalog table.](docs/figures/en-US/rules.png "The rule catalog reads the rule snapshot of the registered Nacos / Consul. Selecting one of the rule family cards filters the catalog below, and '5 / 5 bindings fully read' means the snapshot came back complete.")

The Rules page is the most complex page in the console. It carries three jobs at once: **see what is configured now**, **confirm what the runtime actually loaded**, and **change something safely**. This page separates them with a two-column navigation: the left column holds four main stages, and the right column expands four steps under "Rule maintenance".

## The four main stages and the four steps

| Main stage                | What question it answers                                                | Which panels it holds                                                                                                                                                                                                   |
| :------------------------ | :---------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rule catalog              | What rules the configuration center holds now                           | The configuration center rule catalog, the rule family cards, the search, the unconfirmed configuration sources                                                                                                         |
| Instance effective status | Which instances really loaded them, and whether the loading succeeded   | The configuration source read status, the instance rule loading status, the historical process observations                                                                                                             |
| Binding management        | What relationship an application has to a configuration center rule set | The rule set binding directory, the rule set binding registration                                                                                                                                                       |
| Rule maintenance          | What the rule you want to change looks like now                         | The rule set editor, the saved drafts, the publication target, the immutable rule versions, the publication progress and instance receipts, the active version and the recovery plan, the most recent backend operation |

The four steps under "Rule maintenance" are used in order: **Edit rule → Saved draft → Versions and publishing → Recovery plan**.

> **Note** Editing, version publishing and the recovery plan all require a rule set binding to be selected first. When no binding is selected, the page tells you directly to "select a rule set first" instead of showing an empty editor.

## The rule catalog: first confirm that what you read is complete

The rule catalog reads rule snapshots directly from the registered Nacos / Consul. At the top of the catalog there is a coverage line, and it decides whether the list below can be treated as the full set:

| Coverage line                        | What it means                            | Consequence                                                                             |
| :----------------------------------- | :--------------------------------------- | :-------------------------------------------------------------------------------------- |
| X / Y bindings read in full          | Every binding was read                   | The list is trustworthy                                                                 |
| Only X / Y bindings confirmed so far | Some bindings were not read or are stale | The list is **incomplete**; you cannot conclude from it that "there are no other rules" |

Each row of the catalog gives the resource name, a threshold summary, the configuration source, the configuration read status (current snapshot / stale snapshot) and the instance usage. A stale snapshot keeps the content from the last successful read, but it is explicitly marked as such.

### The rule family cards: the five families are chosen here

Above the catalog there are five cards: flow control, circuit breaking, system protection, authority and hot parameter. Clicking "View this type" filters the catalog below to that family. The cards are **filters**, not creation entry points.

### The rule details: four sections

Opening one rule expands the detail sections:

| Section               | What it gives                                                                                                    | What you cannot conclude from it                                                        |
| :-------------------- | :--------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------- |
| Configuration details | The field values of that rule in the configuration center and the snapshot checksum                              | Anything beyond the freshness of the snapshot                                           |
| Loaded instances      | Which instances confirmed the load, which confirmed that they do not include it, and which are still unconfirmed | Whether the instances that are not listed have loaded it                                |
| Request effect        | The hits and blocks per rule                                                                                     | Without a per-rule read model, you cannot attribute resource-level traffic to this rule |
| Publication history   | The publication records of this binding                                                                          | It cannot be attributed to a single rule                                                |

> **Note** The three numbers under "instance usage" have to be read separately: confirmed loaded, confirmed not included, and **unconfirmed**. The third category is not "not loaded"; it is insufficient evidence.

## Instance effective status: two sets of readings

| Panel                            | What it reads                                           | The key distinction                                                       |
| :------------------------------- | :------------------------------------------------------ | :------------------------------------------------------------------------ |
| Configuration source read status | The actual result of reading Nacos / Consul per binding | **Target missing** and **confirmed empty rules** are two different states |
| Instance rule loading status     | The load receipts of the registered runtime instances   | It relies only on the receipts persisted by the Collector                 |

Telling these two states apart matters: when the binding points at a target that does not exist, the configuration was written to the wrong place; when the target exists but the rules are empty, the rules really were cleared. The first needs a changed binding, the second needs changed rules.

> **Note** When the catalog coverage is insufficient, the page shows "observation is incomplete; do not infer that rules are unused or the configuration is empty". That sentence means exactly what it says, and you should not work around it to draw a conclusion.

## Binding management: where the rules come from

The binding directory lists the bindings between applications and configuration center rule sets. Registering a new binding requires the environment, the application, the configuration center type, the addressing location (namespace or datacenter) and the rule set identifier.

A binding has seven states:

| State                        | Meaning                                                             |
| :--------------------------- | :------------------------------------------------------------------ |
| Currently contains rules     | The binding is usable and the target holds rules                    |
| Confirmed empty              | The binding is usable, but the target is confirmed to hold no rules |
| Target missing               | The target does not exist                                           |
| Content invalid              | Content was read but does not follow the agreement                  |
| Not supported by the profile | The profile cannot cover this binding                               |
| Source unavailable           | It cannot be read                                                   |
| Not read yet                 | It has never been read                                              |

## Rule maintenance: a change goes through all four steps

The complete path of changing one rule:

1. **Edit rule**: change the fields in the rule set editor and save them as a draft. Saving a draft **does not change** the running rules.
2. **Saved draft**: the draft can be edited further, and you can look at the rule baseline it corresponds to.
3. **Versions and publishing**: freeze the draft into an immutable version, then publish it to the configuration center. Freezing has 5 preconditions, and publishing has 5 as well.
4. **Recovery plan**: when you need a delayed activation or a rollback, you manage the plan here.

| Action                | Channel                                                                      | When a precondition is not met                                                 |
| :-------------------- | :--------------------------------------------------------------------------- | :----------------------------------------------------------------------------- |
| Validate              | The \`validate\` / \`diff\` outside \`POST /api/v1/rulesets/{bindingId}/commands\` | It returns the problems with their concrete paths                              |
| Freeze into a version | \`freeze_version\`                                                             | 422 \`rule_freeze_not_ready\`                                                    |
| Publish               | \`publish\`                                                                    | 409 \`conflict\` (the dialog intent and the current facts differ field by field) |

> **Note** **A rollback is not a separate command.** Rolling back means "publish again with the current configuration as the baseline". So a rollback also leaves a version and an audit record behind.

> **Note** The browser does not run the schedule. The activation and the restoration are executed in the background, and closing the browser does not cancel them.

## Why the time range on the Rules page does nothing

The Rules page also has environment, application and time range at the top, but every read on the Rules page is a **point-in-time read** — it reads the current snapshot, the current catalog, the current draft, the current version and the current receipt. The \`range\` / \`from\` / \`to\` in the URL are only passed through on this page; nothing consumes them.

> **Note** To see "the rule change history of a certain period", go to the publication history in the rule details, or to the operation audit in System management. The Rules page itself does not filter rules by a time window.

## Confirm these four things before you change anything

1. What profile is marked on the binding, and which rule families it supports.
2. The unit of the fields in this rule: seconds or milliseconds, and whether the ratio runs from 0 to 1 or from 0 to 100.
3. Which fields the current draft changed relative to the current version — use \`diff\`, do not rely on memory.
4. Whether all the publication preconditions are met, especially "the dialog intent and the current facts differ field by field": if the page has already changed between the moment the dialog opened and the moment you confirm, the publication is rejected.

## Further reading

- [Sentinel Dashboard](https://sentinelguard.io/en-us/docs/dashboard.html)
- [Sentinel General Configuration](https://sentinelguard.io/en-us/docs/general-configuration.html)
`;export{e as default};
