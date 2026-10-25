---
title: Accounts, roles and permissions
summary: Who can see what, who can change what, and where to change it.
prerequisite: An administrator account.
outcome: Give a colleague an account that can only look and not change, and know
  which layer actually enforces permissions.
---

## Two roles, two capabilities

The permission model is deliberately small: two capabilities and two roles. There is no tenant hierarchy and no approval flow.

| Role                | Holds capabilities         | Typical use                                                 |
| :------------------ | :------------------------- | :---------------------------------------------------------- |
| Administrator admin | metrics:view + rules:write | The person who configures and publishes rules               |
| Viewer view         | metrics:view only          | On-call observation; people who only need to look at charts |

> **Note** The two capabilities can be granted independently in the protocol, but the two built-in roles bundle them together. When the interface lacks a permission it hides the entry point rather than disabling it with a hint.

## Create a viewer account

The account maintenance page has exactly three business inputs: username, password and role. There are no other fields to fill in.

1. Open the account maintenance page and click new account.
2. Fill in the username and the password; the password must be 8 to 32 UTF-16 code units long.
3. Choose the role. Choose viewer here.
4. Submit. The submission carries an idempotency key, so clicking twice does not create two accounts.
5. If the submission result is unknown, do not simply do it again — refresh the account list first to confirm the state.

## Change the role of an account

Role binding lives on its own page. You must select the target account explicitly before acting; the system does not pick the first one for you.

1. Open the role binding page and explicitly select an account in the account list.
2. Check that account's current role and status.
3. Choose the target role and submit.
4. The built-in administrator account is protected; you cannot change its role.
5. The last valid administrator cannot be demoted, or the system would lose its administrative entry point.

## Administrator account lifecycle actions

Account row actions include role binding, enable/disable, password reset and delete. Generate password fills a locally generated 24-character secure password that you can view, copy, hide or edit; only Reset submits it. Reset requires one new password, revokes every target session and leaves disabled accounts disabled.

Deletion hides the account and prevents login while reserving its username and retaining audit/publication history. A built-in administrator cannot be disabled, demoted or reset by another administrator. The signed-in administrator can reset their own password here, including the built-in admin; the reset revokes all sessions and requires a new login. Self deletion is blocked. The last active administrator cannot be disabled, demoted or deleted.

> **Note** Inspect the original operation when its outcome is unknown. Read the latest record on revision conflict; do not replay an uncertain write.

## Change your own password

Any signed-in user can use the change-password page; it needs only the current password and the new one. A successful change ends the current session as well, so you have to log in again.

1. Open the top-right avatar menu and choose Change password. Both administrators and viewers have this entry.
2. Fill in the current password, the new password and a confirmation. The confirmation field only prevents typos locally.
3. Log in again after submitting.

> **Note** Repeated wrong passwords block an account temporarily once the threshold is reached within a statistical window. The block duration and the window come from the deployment configuration, so 'it worked a moment ago' does not necessarily mean the password was right — you may simply have tried too many times.

## Which layer actually decides permissions

Hiding write entries in the browser is experience, not a security boundary. The real enforcement happens on the server: every write request re-checks the role of the current session, returning 403 when the permission is missing and 401 when the session is missing.

So 'the button is visible' does not mean the endpoint will let you through, and 'the button is hidden' does not mean you can bypass it by calling the endpoint directly.

| Layer    | What it does                                                                        | What it does not do                                                     |
| :------- | :---------------------------------------------------------------------------------- | :---------------------------------------------------------------------- |
| Frontend | Decides which entry points to show, based on the capability snapshot in the session | Makes no 'if you have permission then you may write' business judgement |
| Server   | Re-evaluates the role and the capabilities on every request                         | Does not trust role claims sent by the browser                          |

## Login and sessions

Login, logout and password change are server-side protocol actions; the browser only initiates them. The list below gives the endpoints and the behavior, and then the points people trip over.

The session lasts 28800 seconds by default, controlled by the deployment-side SENTINEL_CONSOLE_SESSION_TTL_SECONDS. A session is a fact recorded on the server; the browser only holds a cookie, and once the server record expires the leftover cookie is no longer valid either.

Logging out waits for the server to confirm. Until the logout request returns success, the page neither retries for you nor pretends you are logged out. When the result is unknown the page states the current status explicitly instead of jumping back to the login page — 'not sure whether I logged out' and 'logged out' call for different handling.

A successful password change invalidates the current session immediately, requires logging in again, and clears both the session cookie and the CSRF cookie on the server. When the result is unknown, do not resubmit; query the state first and then decide whether to retry.

| Action                    | Endpoint and request body                                                                                                              | What happens on success                                                                                                            |
| :------------------------ | :------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------- |
| Login                     | POST /api/v1/auth/login, body exactly username and password                                                                            | An administrator lands on #/accounts, a non-administrator on #/change-password                                                     |
| Logout                    | POST /api/v1/auth/logout                                                                                                               | The server invalidates the session and clears the session cookie and the CSRF cookie                                               |
| Change your own password  | POST /api/v1/auth/password, body exactly currentPassword and newPassword                                                               | The current session is invalidated and you must log in again                                                                       |
| Read the current identity | GET /api/v1/auth/me                                                                                                                    | Returns the account, the role and the capabilities of the current session                                                          |
| Repeated login failures   | The same client source reaches the threshold within one statistical window                                                             | Login is rejected for the block duration, returning rate_limited and the remaining wait time                                       |
| Block policy parameters   | SENTINEL_CONSOLE_LOGIN_FAILURE_THRESHOLD, SENTINEL_CONSOLE_LOGIN_FAILURE_WINDOW_SECONDS, SENTINEL_CONSOLE_LOGIN_BLOCK_DURATION_SECONDS | All three are required deployment configuration with no defaults; if one is missing the service will not start on a guessed policy |

> **Note** Changing your password during a block does not lift the block. The failure counter for password changes and the failure counter for login are two independent counters that share the same policy parameters, so the only way out of a login block is to wait out the block duration.
