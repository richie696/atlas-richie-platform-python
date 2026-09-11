# Atlas Richie OAuth JOSE Adapter

This optional adapter validates OAuth JWT access tokens with JOSERFC and its
cryptography backend.  Applications depend on it only when local JWT/JWKS
validation is needed; opaque-token deployments can use the core
introspection port instead.
