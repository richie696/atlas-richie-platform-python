const e=`---
title: Connect Nacos / Consul and register bindings
summary: Read the existing rules first, then open managed publication.
prerequisite: An administrator account; the target network already in the
  allowlist; the source's credentials ready.
outcome: Locate the correct configuration location and tell 'save' apart from 'publish'.
---

## A source and a binding are two different things

A source registration answers 'how do I reach this configuration center'; a rule binding answers 'where do this application's rules live'. Both are needed, and rules cannot be read without them.

A rule binding has four parts: environment, application, rule family and configuration location, plus the runtime profile that decides which fields the binding allows. The service and the console must point at the same configuration location — the most common reason for 'the rules cannot be read'.

The browser uses only the Console API to register sources, enter targets and read status; it never connects directly to Nacos / Consul. Backend provider adapters resolve credentials, read and write configuration, and perform independent read-back. The Runtime reads rules from the configuration center and reports runtime facts to the Collector. These are separate paths.

| Configuration center | Fields of the configuration location |
| :------------------- | :----------------------------------- |
| Nacos                | namespace ID, group, Data ID         |
| Consul               | datacenter, full KV key              |

## Three authentication methods

You choose the authentication method when registering a source. Do not carry passwords or tokens in the address.

| Method                               | What it means                                                                               | Who it suits                                                               |
| :----------------------------------- | :------------------------------------------------------------------------------------------ | :------------------------------------------------------------------------- |
| None                                 | The target requires no authentication                                                       | Local or intranet test environments                                        |
| Direct credentials                   | The console holds the username and password itself and stores them encrypted                | A single console instance manages the source                               |
| Deployment-side credential reference | The console stores only a reference; the real credential is injected by the deployment side | Multi-instance deployments, or deployments that need to rotate credentials |

> **Note** A credential reference does not force you to run a key management service; it only requires that the console does not hold the credential itself.

## Register a source

Register it in the Connections and collection tab of System management. Registering only records how to connect; it changes nothing in the configuration center.

1. Open System management and stay on the Connections and collection tab.
2. Choose the provider type Nacos or Consul and fill in the service address.
3. Choose the authentication method and fill in the corresponding information.
4. Test the connection. When it fails, read the reason in the probe results first, then the network allowlist and the certificate.
5. Save. The source then appears in the source list and can be selected when you create bindings.

## Register a rule binding

Register it on the Rules page. The binding decides where the console reads from, where it writes, and what kind of rule may be written.

1. Open the Rules page, find the rule binding catalog and click register rule set binding.
2. Choose the deployment environment and the application identifier. When the catalog is empty you can type the identifier you configured initially.
3. Choose the rule family. Bindings are separated by family, and different families are independent bindings.
4. Choose the configuration source and fill in the configuration location using the table above.
5. Choose the runtime profile. Only fields the profile supports can be published.
6. After saving, the binding appears in the rule catalog and the configuration center can be read.

> **Note** The profile sets the capability ceiling. A field existing in the form does not mean the current binding can publish it — validation before publication will reject it, but the better practice is to fill in only what the profile allows in the first place.

## Empty array, missing target and failure are different

These three look different in the interface, but beginners often treat them as one. Telling them apart saves half the troubleshooting time.

| Read state                        | What it means                                                      | Next step                                                                              |
| :-------------------------------- | :----------------------------------------------------------------- | :------------------------------------------------------------------------------------- |
| Empty array                       | The location really exists and contains no rules at all            | A normal state; you can start writing the first rule                                   |
| Target missing                    | The location does not exist in the configuration center            | Check the configuration location for typos, or that nothing has been created there yet |
| No permission / connection failed | Nothing could be read                                              | Check the credentials and the network; this does not mean 'there are no rules here'    |
| Last-known-good retained          | This read failed and what is shown is the previous successful read | Fix the connection, then read again; the content on screen is not the current state    |

> **Note** Publication is a wholesale replacement, not an incremental patch. That makes 'read 0 rules' and 'cannot read' completely different in consequence: the first may mean you just cleared it, the second may mean the configuration center is down.

## In what order to check when a source will not connect

Connection failures belong to different layers, and working through them in order is faster than retrying. The steps below cover the address, the configuration location, the credentials, the network allowlist and the trust root, and then a retest.

1. Check the address format first. The service address may only be http or https, with no userinfo, query string or fragment, and the host must be either a valid DNS name or an IP address in canonical form. Passwords and tokens do not belong in the address; carry them in the authentication method instead.
2. Then check the configuration location. Consul uses datacenter plus the full KV key; Nacos uses the three parts namespace ID, group and Data ID. A wrong configuration location still passes the connection test, but the read finds nothing — this is the main source of 'it connects but the rules cannot be read'.
3. Confirm the credentials. There are three authentication methods: none, direct credentials and deployment-side credential reference. The Console backend holds and encrypts direct credentials; incorrect values cause authentication failure. A credential reference requires deployment-side injection, resolved by the backend when connecting. The browser never reads credentials back or uses them to connect directly to the configuration center.
4. Confirm the network allowlist. The source target allowlist format is provider|hostname|cidr,cidr|port,port, with multiple entries separated by semicolons. The provider name and the hostname must match the real target, the port must be in the allowed list, and the CIDRs must cover the egress address of the deployment side.
5. Confirm the TLS trust root. A source signed by a private CA needs a PEM CA bundle configured, otherwise the handshake fails. A configured trust root does not let you skip verification — certificate verification and hostname verification still apply.
6. Retest the connection last. The probe returns a limited set of failure reasons with no arbitrary exception text: a source check returns connection, authentication and unsupported; the connections view in System management returns network, authentication, unsupported, not-configured and no-probe. Confirm which set you are looking at, then work through the reasons.

| Check                             | How to confirm                                                                          | When it fails                                                                                                                                             |
| :-------------------------------- | :-------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Service address format            | http or https only, with no userinfo, query string or fragment                          | Remove the password or token from the address and carry the credential in the authentication method                                                       |
| Configuration location            | Consul uses datacenter and the full KV key; Nacos uses namespace ID, group and Data ID  | When the connection test passes but the read fails, come back to this item first                                                                          |
| Credentials                       | One of none, direct credentials or deployment-side credential reference                 | Wrong direct credentials are an authentication failure; for a reference, check the injection on the deployment side                                       |
| Source target allowlist           | provider\\|hostname\\|cidr,cidr\\|port,port, with multiple entries separated by semicolons | Any mismatch in the provider name, the hostname or the port is rejected                                                                                   |
| TLS trust root                    | A private CA needs a PEM CA bundle                                                      | Without a trust root the handshake fails; after adding one, certificate and hostname verification still apply                                             |
| Failure reason in the test result | A source check returns connection, authentication or unsupported                        | connection points to the network and the allowlist, authentication to the credentials and the trust chain, unsupported to the provider and the parameters |
`;export{e as default};
