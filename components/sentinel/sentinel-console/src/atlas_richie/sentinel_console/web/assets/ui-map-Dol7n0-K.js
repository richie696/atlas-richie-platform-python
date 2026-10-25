const e=`---
title: "UI map: what each page is responsible for"
summary: Find a page by capability, find a capability by page.
prerequisite: Knowing the rough sections of the left navigation is enough.
outcome: When you know what you want to do, you know where to click; when you
  cannot find it, you know which term to search.
---

## Seven navigation items and their URLs

Every console page has a URL you can share directly (hash routing). The URL carries the filters and the time range, so copy it to a colleague and they open the same screen.

| Navigation item            | URL            | Question it answers                                                          | Who can open it                                                     |
| :------------------------- | :------------- | :--------------------------------------------------------------------------- | :------------------------------------------------------------------ |
| Overview                   | #/overview     | Which applications need attention                                            | View metrics                                                        |
| Applications and instances | #/applications | Which instance the problem sits in                                           | View metrics                                                        |
| Rules                      | #/rules        | Where the configuration comes from and how to change it safely               | View metrics; write operations also need the write-rules capability |
| Realtime                   | #/realtime     | How traffic, latency, blocking and resource pressure interact                | View metrics                                                        |
| Fault analysis             | #/faults       | What happened first and which next step the evidence supports                | View metrics                                                        |
| System management          | #/system       | How to connect the configuration center and monitoring and confirm the chain | Administrator                                                       |
| Documentation              | #/docs         | This page                                                                    | Public                                                              |

> **Note** The documentation center is a public page: you can open it and read the manual even when the console is not initialized, you are not logged in, or a backend dependency is unavailable. Every other page requires login and is gated by permission.

## Filters and time range at the top

Overview, Applications and instances, Rules, Realtime, Fault analysis and System management all offer the same filters at the top: environment, application and time range. Environments come from registered and bound scopes, not from scanning your servers automatically; applications come from the authorized observation catalog.

The time range has two presets, 'Last 15 minutes' and 'Last 1 hour', and some pages also accept an explicit start and end time. Both the range and the filters are written into the URL, so refreshing, sharing and going back all return to the same screen.

1. Choose the environment first, then the application: the environment determines what the application catalog contains.
2. Choose the time range. Before comparing two curves, confirm that they use the same range.
3. When you need to share a troubleshooting result, copy the URL from the address bar.

## Seven tabs inside System management

System management is not a single page but seven tabs. The active tab is also written into the URL, distinguished by the view parameter, so each one can be shared and refreshed on its own.

| Tab                        | URL parameter    | What is inside                                                                              |
| :------------------------- | :--------------- | :------------------------------------------------------------------------------------------ |
| Connections and collection | view=connections | Configuration source registration, monitoring source registration, connection probe results |
| Permissions and audit      | view=permissions | The permissions and role declarations of the current session                                |
| Protocol and versions      | view=protocol    | Protocol coverage and version information                                                   |
| Operation audit            | view=audit       | The trail of operations                                                                     |
| Account maintenance        | view=accounts    | Adding, removing, enabling and disabling accounts in the system                             |
| Role binding               | view=roles       | Bind the administrator or viewer role to an account                                         |
| General settings           | view=settings    | The system-level general settings items                                                     |

## Three separate account entry points

The account features are not in the main navigation; they live in three separate entry points. Their URLs and permissions differ, so do not go looking in the wrong place.

| Entry point         | URL               | Who can open it    | What it does                                                       |
| :------------------ | :---------------- | :----------------- | :----------------------------------------------------------------- |
| Account maintenance | #/accounts        | Administrator      | View the account list, create accounts, disable or enable accounts |
| Role binding        | #/roles           | Administrator      | Bind the administrator or viewer role to selected accounts         |
| Change password     | #/change-password | Any signed-in user | Change your own password                                           |

> **Note** The change-password page only changes your own password; you cannot target another account with a URL parameter.

## How to search when you cannot find a feature

The search box on the left covers the titles, summaries, body text, steps, notes and code samples of every article. An empty query returns to the current article; a non-empty query shows matching results, and when there are none the page suggests a shorter term.

When a documentation link is dead the page says so explicitly — 'this document does not exist or the link has changed' — and offers a way back to the start, instead of rendering a blank page.

1. Search a concrete noun first: an environment variable, a command or a field name, for example METRICS_CLIENT_PKCS12, setup-window or statIntervalMs.
2. If that fails, search an action word: publish, roll back, load, blank.
3. If you still cannot find it, the capability may genuinely not be implemented yet — the documentation does not describe behavior that does not exist.

## Which parameters the URL carries

A console URL is a hash route followed by a query string. The parameters are a projection of the interface state: the selected application, the time range, the selected object and the active tab are all written in, so copying the URL copies the whole context.

The table below lists each parameter, what it means and where it appears. The same parameter can mean different things on different pages; view is the most typical case. Observation windows are given as exact timestamps, and the console interprets them as a UTC half-open interval [from, to).

| Parameter   | Meaning                                                           | Where it appears                                                                         |
| :---------- | :---------------------------------------------------------------- | :--------------------------------------------------------------------------------------- |
| app         | Identifier of the currently selected application                  | Overview, Applications and instances, Rules, Realtime, Fault analysis, System management |
| env         | Identifier of the currently selected deployment environment       | Overview, Applications and instances, Rules, Realtime, Fault analysis, System management |
| range       | Relative time range: last 15 minutes or last 1 hour               | Overview, Applications and instances, Rules, Realtime, Fault analysis                    |
| from        | Start of the observation window, an exact timestamp               | Overview, Applications and instances, Rules, Realtime, Fault analysis                    |
| to          | End of the observation window, an exact timestamp                 | Overview, Applications and instances, Rules, Realtime, Fault analysis                    |
| view        | Sub-view identifier inside a page                                 | Rule family filter on the Rules page; tab on the System management page                  |
| instance    | Identifier of the currently selected instance                     | Overview, Applications and instances, Realtime, Fault analysis                           |
| account     | Identifier of the account being operated on in the identity pages | Account maintenance, Role binding                                                        |
| binding     | Exact identifier of a rule configuration binding                  | Rules page                                                                               |
| version     | Rule version identifier                                           | Rules page                                                                               |
| publication | Exact identifier of a managed publication                         | Rules page                                                                               |
| section     | The main stages and steps of the Rules page                       | Rules page                                                                               |
| q           | Search term                                                       | Documentation                                                                            |
| severity    | Severity filter for the fault timeline                            | Fault analysis                                                                           |
| category    | Category filter for the fault timeline                            | Fault analysis                                                                           |
| cursor      | Pagination cursor of the fault timeline                           | Fault analysis                                                                           |
| scope       | Collection scope of the metrics                                   | Realtime                                                                                 |
| returnTo    | Local route to return to after a successful login                 | Login page                                                                               |

> **Note** \`view\` does not take the same values on the Rules page and on the System management page. The Rules page takes flow, degrade, system, authority and param; System management takes connections, permissions, protocol, audit, accounts, roles and settings. The two sets are not interchangeable — pasting one page's URL into another lands on the wrong view.

## Which states do not go into the URL

Not every interface state is written into the URL. The ones below are **lost on refresh**, and they do not affect the links you share:

| Page            | The states that do not go into the URL                       |
| :-------------- | :----------------------------------------------------------- |
| Overview        | The application name filter and the pagination               |
| Account list    | The filter conditions and the pagination                     |
| Operation audit | The filter conditions                                        |
| Role binding    | The directory filter and the pagination                      |
| Rules page      | The time range \`range\` and the start and end \`from\` and \`to\` |

> **Note** The time range of the Rules page belongs to this category: it is passed through, but every read on the Rules page is a point-in-time read and there is no consumer for it. To look up rule changes over time on the Rules page, use the publication history or the operation audit.

The states that do go into the URL are these: the System management tab \`view\`, the target account \`account\` of Role binding, the \`severity\` / \`category\` / \`cursor\` of Fault analysis, the \`section\` / \`binding\` / \`version\` / \`publication\` of the Rules page, and the global environment \`env\`, application \`app\` and time range \`range\` (which the four pages Overview, Applications and instances, Realtime and Fault analysis consume).
`;export{e as default};
