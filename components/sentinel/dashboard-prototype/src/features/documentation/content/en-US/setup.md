---
title: First-run initialization after installation
summary: Everything between the installation and a usable console, explained in
  one place.
prerequisite: A machine that can reach the database and the configuration
  center; Python 3.12 or newer.
outcome: Complete the one-time initialization, then use the console normally
  from the login page.
---

## What to prepare first

The package does not create the database, the configuration center or the monitoring backend for you. Prepare the items below in advance; if one of them is missing the service fails safely at startup instead of picking something for you.

| Item                       | Requirement                                                                      | Notes                                                                                                    |
| :------------------------- | :------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------- |
| Database                   | PostgreSQL or MySQL (production); SQLite (local single-process development only) | SQLite accepts no network credentials and does not appear in the database target allowlist               |
| Configuration center       | One Nacos or Consul instance                                                     | At least readable; later publications also need write access                                             |
| Persistent state directory | A writable directory                                                             | The setup-window state, the runtime locator files and the first-run lock live here                       |
| Keyring                    | base64-encoded, each key at least 32 bytes after decoding                        | There is one set each for locator file encryption, source credential encryption and command fingerprints |
| Browser origins            | An exact list of http(s) origins                                                 | No paths allowed and no wildcards                                                                        |
| Target allowlist           | The network ranges and ports of the database and the configuration center        | The format is type\|cidr\|port;type\|cidr\|port                                                          |

## Install and start

Pick the extra that matches your database. server is a prerequisite for running the service; the Nacos publication path also needs nacos-grpc.

1. Install the package and confirm that the CLI works: sentinel-console docs lists the documentation bundled with the current release.
2. Prepare the deployment environment variables. Required items include the setup-window state path, the runtime locator file and its keyring, the first-run lock path, the idempotency key, the database target allowlist, the source target allowlist, the browser origin list, the login failure threshold and window, and three independent keyrings.
3. Open the setup window explicitly: this never happens on its own, and while the window is closed the service still starts but offers no setup entry point.
4. Start the service. If configuration validation fails, the service exits immediately and names the missing item.

```bash

pip install 'atlas-richie-sentinel-console[server,postgres]'
pip install 'atlas-richie-sentinel-console[server,mysql]'
sentinel-console docs quickstart
sentinel-console docs reference
```

> **Note** In the startup parameters the listen address defaults to 127.0.0.1 and the port to 8000. Change the bind address only when other machines really have to reach it, and configure the browser origins at the same time.

## The setup wizard: authorize first, then four steps

Initialization is a one-time process governed by the server. While the window is open, opening the console URL in the browser enters the wizard; when it finishes the server closes the window and any deep link is redirected to the login page.

1. Authorize: a loopback deployment on the local machine uses code-free authorization; a remote deployment needs an operator code supplied by the deployment side.
2. System storage: choose the database type, fill in the connection details and click test connection to verify reachability.
3. Built-in administrator: fill in the username and the password. The system neither generates nor displays any default password.
4. Rule source: choose Nacos or Consul, fill in the service address and the authentication method, and test the connection.
5. Confirm and submit: check the summary and submit. The submission carries an idempotency key, and resubmitting the same key does not start a second initialization.

## Password rules and login

The administrator password must be 8 to 32 UTF-16 code units long. Validation and transport both handle it as-is, with no trimming and no Unicode normalization. A username must not be empty once leading and trailing whitespace is removed.

There are only two roles. The administrator holds both the view-metrics and the write-rules capability; the viewer holds only the view-metrics capability.

| Role                | Capabilities              | Pages it can open                                                                    | What it can do                                                             |
| :------------------ | :------------------------ | :----------------------------------------------------------------------------------- | :------------------------------------------------------------------------- |
| Administrator admin | View metrics, write rules | All six workspaces plus the account pages                                            | Register sources, create bindings, edit and publish rules, manage accounts |
| Viewer view         | View metrics              | Overview, Applications and instances, Rules, Realtime, Fault analysis, Documentation | Read charts, trends, the rule catalog and events; cannot change anything   |

> **Note** There is no command line entry point for account operations; they can only be done on the account maintenance and role binding pages. Changing your own password happens on the change-password page, and any role can change its own.

## What you should see afterwards

After initialization succeeds there are four signals you can verify immediately.

1. The browser returns to the login page; log in with the administrator account you just created.
2. You land on the account maintenance page, which shows that the account exists and its role is bound.
3. Open the Connections and collection tab in System management; the rule source you registered shows as connected.
4. Run sentinel-console setup-window status on the command line; the output setup-window=closed shows that the setup window has closed.

> **Note** The health check only reflects whether the process can serve requests; it does not reflect the database, the configuration center or the monitoring chain. To see the chain state, check the probe results in the Connections and collection tab of System management.

## When initialization gets stuck

Failures during initialization usually produce a narrow set of messages. Work through them in this order: confirm the window, then the authorization, then test each item, then read the receipt.

1. Confirm the setup window first. Run sentinel-console setup-window status; the output setup-window=closed means the window is closed. A missing state file is treated the same way — the wizard being unreachable then is the expected result, not a fault. Reopening it is an explicit action by the deployment side: sentinel-console setup-window open, after confirming that the authorization boundary still holds.
2. The window is open but the wizard will not load: look at the authorization step first. Code-free authorization on the local machine requires the service to bind to a loopback address, every browser origin to be a loopback origin, and no trusted reverse proxy to be configured — all three must hold at the same time. A remote deployment must use an operator code, whose credential is held by the deployment side; do not fill in an arbitrary value.
3. If the database test fails, read the failure reason first. For a connection reason check the network and the allowlist; for an authentication reason check the username and password; unsupported means this set of parameters is outside the supported range.
4. If the source test fails, read the failure reason first, then the authentication method and the trust root. When the console holds direct credentials, check the credentials themselves; when you use a deployment-side credential reference, check that the reference has been injected on the deployment side. A source signed by a private CA needs a trust root configured, otherwise it stops at the handshake.
5. If the submission returns idempotency_conflict, check whether the header and the body agree: an initialization submission must carry exactly one Idempotency-Key header, and its value must equal the requestKey in the body.
6. If the submission result is unknown, do not resubmit under a new key — a new key bypasses the idempotency protection and can produce a second initialization. Query the receipt with the same requestKey: GET /api/v1/system/bootstrap/operations/{request_key}.

| Symptom                                                 | Check first                                                                   | Usual cause                                                                                                                                                                                     |
| :------------------------------------------------------ | :---------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The wizard does not load and you land on the login page | sentinel-console setup-window status                                          | The setup window is closed, or the state file is missing; a missing file is always treated as closed                                                                                            |
| The authorization step fails                            | The bind address, the browser origin list and the trusted proxy configuration | A remote deployment needs an operator code; code-free authorization on the local machine requires a loopback bind, loopback-only origins and no trusted proxy                                   |
| The database test fails                                 | The failure reason and the database target allowlist                          | The allowlist format is type\|cidr\|port, with multiple entries separated by semicolons; SQLite accepts only {"kind":"sqlite"}, and the path must be absolute with an existing parent directory |
| The source test fails                                   | The failure reason, the authentication method and the trust root              | The direct credentials are wrong, or the deployment-side credential reference was never injected; a private CA has no trust root                                                                |
| The submission returns idempotency_conflict             | The Idempotency-Key header and the requestKey in the body                     | There must be exactly one header, and its value must equal requestKey exactly                                                                                                                   |
| The submission result is unknown                        | GET /api/v1/system/bootstrap/operations/{request_key}                         | Resubmitting under a new key bypasses the idempotency protection; query the receipt with the same requestKey instead of starting a new one                                                      |
| You are unsure what an error code means                 | The HTTP status code and the error code                                       | invalid_request is 400, csrf_failed and bootstrap_unauthorized are 403, idempotency_conflict is 409, service_unavailable is 503                                                                 |
