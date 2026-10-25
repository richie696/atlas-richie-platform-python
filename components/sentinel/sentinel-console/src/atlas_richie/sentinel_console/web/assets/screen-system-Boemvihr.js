const e=`---
title: "System management and accounts: onboarding, permissions and the audit trail"
summary: What each of the seven tabs manages, and how to tell the three account
  entry points apart.
prerequisite: You are signed in as an administrator.
outcome: You know in which tab to register a configuration center, in which tab
  to look up the audit, and which entry point the account operations belong to.
---

![The "Connections and collection" tab of System management: at the top are the seven tabs, below them is the runtime connections and collection table, giving the probe results and the probed capabilities of the three paths — rule configuration center, metrics backend and reporting collector — row by row.](docs/figures/en-US/system-connections.png "The seven tabs are Connections and collection, Permissions and audit, Protocol and versions, Operation audit, Account maintenance, Role binding and General settings. The tab state is written into the URL, so each one can be shared on its own.")

System management is only open to administrators. It is not a "settings" page; it is a set of **boundary declarations**: what you connect, who can see, which protocol version you are on, and who changed what.

## The seven tabs

| Tab                        | URL parameter      | What it manages                                                                      |
| :------------------------- | :----------------- | :----------------------------------------------------------------------------------- |
| Connections and collection | \`view=connections\` | Configuration center registration, monitoring source registration, connection probes |
| Permissions and audit      | \`view=permissions\` | The permissions and role declarations of the current session                         |
| Protocol and versions      | \`view=protocol\`    | Protocol coverage and version information                                            |
| Operation audit            | \`view=audit\`       | The trail of operations                                                              |
| Account maintenance        | \`view=accounts\`    | Adding, removing, enabling and disabling accounts in the system                      |
| Role binding               | \`view=roles\`       | Binding a role to an account                                                         |
| General settings           | \`view=settings\`    | The general settings items                                                           |

> **Note** The tab id is written into the URL, so it can be shared and refreshed on its own. When the \`view\` value in the URL is illegal it falls back to the first tab (Connections and collection); it does not "pick the closest one".

## Connections and collection: registering a configuration center

This is the only tab in the page that has a state machine. A registration goes through four steps from filling in the form to taking effect:

1. **Fill in**: connection name, configuration center type (Nacos / Consul), service address, addressing location (namespace identifier or datacenter), rule set identifier and authentication method.
2. **Local validation**: checks the name, the address format and the credentials required by the current authentication method.
3. **Test connection**: a read-only probe only; it **does not register, does not write rules and does not grant publishing rights**.
4. **Save the registration**: writes the registration record into the Console.

After saving there are four possible outcomes:

| Outcome         | What it means                                             | What you should do                                                |
| :-------------- | :-------------------------------------------------------- | :---------------------------------------------------------------- |
| Accepted        | The request has been received, the outcome is not settled | Wait                                                              |
| Confirmed       | The registration succeeded                                | You can go on to bind the rule set                                |
| Rejected        | The backend refused it                                    | Handle it according to the returned code                          |
| Outcome unknown | No definite result was obtained                           | **Do not resend it**; you can only inspect the original operation |

> **Note** **Changing any field immediately invalidates the previous test result.** Changing the configuration center type or the authentication method also clears the credentials you have already entered. That is not a way of clearing what you just typed; it prevents an old probe result from being used to prove a new configuration.

> **Note** When the outcome is unknown, the page clears the credentials and **disables the submit button**, leaving only "Inspect original operation" as an exit. Credentials are never echoed back — the registration record only holds a boolean of "credentials configured / no credentials configured".

### The two safeguards on editing and deleting

| Operation | Protection mechanism                                             | Result on a conflict                                                               |
| :-------- | :--------------------------------------------------------------- | :--------------------------------------------------------------------------------- |
| Edit      | Carries the configuration revision identifier \`expectedRevision\` | 409 "the configuration revision has changed"; the newer version is not overwritten |
| Delete    | Carries the same revision identifier                             | 409 as above                                                                       |

Only one write operation is allowed at a time; a resubmission gets the prompt "an operation is already in progress", together with the \`retryAfterMs\` cooldown.

> **Note** **Deleting only removes the registration and the controlled credentials in the Console; it does not delete the rules in the configuration center.** If a rule binding still references this configuration center, the backend refuses the deletion and tells you to remove the binding first.

## Permissions and audit: what the current session can do

This tab shows the **confirmed snapshot of the current session**: the signed-in account, the account identifier, the current role, the session capabilities (view traffic and resource charts / edit and publish flow control rules) and the granted state of each of them.

There are only two fixed roles: administrator and viewer. This tab does not edit roles and does not add capabilities.

> **Note** What the page displays is **not a security boundary**. The backend still authorizes every request. "Granted" in the interface does not mean the server has already let the action through.

## Protocol and versions: which capabilities this page declares

The Protocol and versions tab gives the protocol coverage and the version information, and it answers "which protocols does the current console know, and up to which version is each one".

> **Note** What it lists is the **declared boundary**, not the runtime reality. A protocol having a name here does not mean your application has connected to it.

## Operation audit: who changed what

The audit trail has six columns: operation time, operating account, operation type, target identifier, execution result, and the request and publication correlation.

| Item              | Value                                                                                                           |
| :---------------- | :-------------------------------------------------------------------------------------------------------------- |
| Time window       | **UTC**, independent of the server's local time zone; the default is the last 24 hours and the limit is 31 days |
| Operation types   | 31 kinds, from account creation to rule binding creation                                                        |
| Execution results | Success / Rejected / Result pending verification                                                                |
| Rows per page     | At most 100                                                                                                     |

An audit row can drill down to the linked publication record.

> **Note** **Audit filters do not go into the URL.** A refresh after filtering loses them. Before you show the audit of a certain period to somebody else, write down the filter conditions.

## General settings

The last tab is General settings. It holds system-level defaults and is unrelated to accounts, connections or protocols.

## The three separate account entry points

The account features are **not in the main navigation**. There are three separate entry points, with different URLs and different permissions:

| Entry point         | URL                 | Who can open it    | What it does                                                         |
| :------------------ | :------------------ | :----------------- | :------------------------------------------------------------------- |
| Account maintenance | \`#/accounts\`        | Administrator      | Account list, create, enable and disable, reset the password, delete |
| Role binding        | \`#/roles\`           | Administrator      | Bind the administrator or the viewer role to a selected account      |
| Change password     | \`#/change-password\` | Any signed-in user | Change your own password                                             |

The "Account maintenance" tab in System management and the standalone entry point \`#/accounts\` point at the same account management flow; the only difference is that the tab is nested in the tab structure of System management.

### The six columns of the account list

Account, role, status, last sign-in, type, actions.

![The account maintenance page: at the top are the account name filter and the status dropdown, below them is the account list, which gives the account, role, status, last sign-in, type and action entry points row by row; on the row of the built-in account that is currently signed in, the delete and disable buttons are disabled.](docs/figures/en-US/accounts.png "The account list is the entry point for deleting an account and for resetting a password. The account that is currently signed in cannot be deleted, and a built-in administrator can neither be disabled nor downgraded, so those two buttons are disabled.")

### The four safeguards on deleting an account

Any of the following stops the deletion: the account is locked, the account is a built-in account, deleting it would leave the system with no active administrator, or the account is the one you are currently signed in with.

> **Note** After the deletion the **account name is kept**, and the audit and publication records are kept as well, but the deletion itself cannot be undone.

### What a password reset does

A password reset immediately revokes every session of that account and invalidates the old password; but it **does not automatically enable a disabled account** — a disabled account is still disabled after its password is reset.

> **Note** The change-password page can only change the password of the account you are currently signed in with; you cannot point it at another account through a URL parameter. After a successful change the server atomically replaces the password hash and revokes every session, and you have to sign in again.

## The complete order for onboarding a configuration center

1. Register the configuration center under "Connections and collection", and click **Test connection** when the form is filled in.
2. After the test passes, save the registration and get a confirmed outcome.
3. Go to "Binding management" on the Rules page and create the rule set binding with the same environment, application and this registration.
4. After the binding succeeds, go to "Instance effective status" and confirm that the runtime really loaded the rules.
5. Go back to "Operation audit" and confirm that all of these steps left a record.

> **Note** The passing test in step 1, the confirmed save in step 2, the successful binding in step 3 and the load receipt in step 4 are **four independent confirmations**. If any one of them was not confirmed, do not assume that the next one already holds.

## Further reading

- [Sentinel General Configuration](https://sentinelguard.io/en-us/docs/general-configuration.html)
`;export{e as default};
