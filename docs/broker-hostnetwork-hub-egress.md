# Restore Broker access to the host-network Hub

Atlantic's signed identity continues publishing heartbeats, but its existing
Admin grant stopped renewing on 2026-11-21. Applying the reviewed 0.3.34 Agent
image completed a real rollout (generation 33 observed, one updated/Ready
replica); it did not repair renewal. The grant and its credential were not reset.

The actual Hub is a host-network workload on R640 (10.250.0.128:8080).
`among-clusters-broker-hub` allowed only a Hub Pod-label endpoint. A real
anonymous identity GET from Broker endpoint 3921 (10.68.9.155, identity 17572)
timed out while Cilium recorded `Policy denied`, identity 17572 to host identity
1 on TCP 8080. The same public path from the node host returned HTTP 200. No
request token, response body or packet payload was captured.

[Cilium's entity policy](https://docs.cilium.io/en/stable/security/policy/layer3/#entities-based)
represents host-network containers with host/node identities, not their Pod
labels. Node-selector labels are disabled in this cluster, so this correction
uses the existing native host/remote-node entities without changing global
Cilium settings or restarting agents.

Keep the exact Broker source selector and the original Pod-label destination
rule. Add only node identities on TCP 8080. This allows that single port on
node identities; it does not claim to select one exact Hub Pod. The Broker's
configured destination remains the reviewed internal Hub Service. No world,
cluster-wide Pod identity, other port, RBAC, credential, OIDC or routing change
is included. Rescheduling either component remains supported.

After the signed policy bundle is applied, repeat the same one-shot anonymous
Broker-netns public-identity GET and verify HTTP 200 with no policy drops. Then
observe the original grant UID's natural lastRenewedAt/credential expiry advance
without a restart, TTL extension or manual credential upload. Verify another
scheduled renewal and use the same current Admin plugin for Atlantic API UID,
SSA revision 1 to 2/read-back/cleanup. An Actions apply alone is not recovery.
