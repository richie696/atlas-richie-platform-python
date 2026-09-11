# OAuth 2.1 Component: P1 Design

## Boundary

The Python component mirrors the Java component's protocol responsibilities,
not its Spring runtime.  It is a reusable client/resource-server capability:

- it discovers and parses OAuth metadata, makes token/introspection requests,
  creates PKCE S256 material, manages an in-process token snapshot, and
  defines resource-server validation contracts;
- it does **not** run an Authorization Server, own users/consent/client
  persistence, sign access tokens, or persist refresh tokens;
- an application can embed it in FastAPI, Django, Flask, a CLI, an MCP HTTP
  adapter, or no web framework at all.

The P1 interoperability target is any standards-compliant Authorization Server
and Resource Server using `client_credentials`, `authorization_code` + PKCE,
`refresh_token`, RFC 8414 metadata, RFC 8707 resource indicators, RFC 7662
introspection, and JWT access-token validation through JWKS.  Java, Python and
other runtimes cooperate through those wire contracts, not private adapters.

The component also acts as a remote OAuth/OIDC client for RFC 8628 device
authorization (one explicit token attempt at a time), RFC 7009 revocation,
RFC 7591 dynamic client registration, and OIDC UserInfo.  It does not become
an Authorization Server or schedule device-code polling behind an application's
back; applications retain their own UX, lifecycle, and retry budget.

## Module boundary

```text
atlas-richie-oauth
  contracts, metadata, PKCE, endpoint policy, HTTP token/introspection client,
  in-process token manager, JWKS source, resource authenticator
                 |
                 | owns no JOSE type
                 v
atlas-richie-oauth-jose
  JOSERFC + cryptography adapter: JWT signature and registered-claim checks
```

`oauth` depends only on Atlas Richie contracts and the owned HTTP component.
The only non-platform cryptography dependency is isolated in the named JOSE
adapter.  No framework package is a dependency of either distribution.

## Security invariants

1. Default outbound OAuth endpoints are HTTPS, with no URI user-info or
   fragment.  Internal HTTP requires an explicitly supplied endpoint policy.
2. PKCE only accepts `S256`; verifier generation is cryptographically random
   and validation uses constant-time comparison.
3. `resource` is a validated absolute URI and is matched exactly by the token
   manager.  A token cannot be reused for another protected resource.
4. Required scopes must all be present; configured and request scopes merge
   rather than replace one another.
5. OAuth errors, audit events, and public exceptions never include an access
   token, refresh token, or client secret.
6. JWT algorithm selection is allow-listed by the adapter.  Issuer, audience,
   expiration, subject, and `kid` are mandatory for local JWT acceptance.
7. A missing `kid` forces exactly one JWKS refresh so key rotation is
   supported without silently accepting an unknown key.

## Object design

- **Facade:** `OAuthTokenClient`, `OAuthMetadataClient`, and
  `ResourceServerAuthenticator` provide use-case APIs.
- **Strategy / port:** `OAuthEndpointPolicy`, `OAuthTokenRequester`,
  `TokenValidator`, `JwkSetSource`, and `IntrospectionClient` isolate true
  environmental variation.
- **Adapter:** `JoseJwtTokenValidator` translates JOSERFC into the component's
  `AuthenticatedPrincipal`; JOSERFC values never leak into public core APIs.
- **Stateful façade:** `OAuthTokenManager` owns a lock and immutable token
  snapshots.  It is deliberately process-local; cross-process refresh locks
  and persistent refresh-token rotation remain Authorization Server work.

## Deferred deliberately

DPoP proof signing/verification and replay protection, OIDC ID-token and RP
logout validation, distributed JWKS/introspection cache, and framework HTTP
adapters remain separate increments.  They need an explicit JOSE or storage
adapter plus replay and transport acceptance evidence; this component must not
pretend to provide them without those dependencies.
