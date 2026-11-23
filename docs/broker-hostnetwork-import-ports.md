# Broker access to host-network gateway imports

After fixing the imported Service's unresolved named targetPort, the actual
Broker netns TCP connection at 2026-11-23T08:32:04Z still timed out. The same
source tuple (10.68.9.155:47362) was observed by its endpoint-scoped Cilium drop
monitor after Service DNAT to 10.250.0.128:33768: identity 17572 to host, Policy
denied. No HTTP payload or credential was sent. The gateway is hostNetwork;
its Pod selector does not match the resulting host identity.

Keep the existing Broker source selector and Pod-network destination rule.
Add host/remote-node access only on the existing declared Kubernetes import
listeners 22240/23768/33768 TCP. This allows those ports on node identities,
not an exact Gateway Pod. It does not allow world, cluster, all ports, new
listeners or new grants. The regression ties this set to existing gateway
imports and covers the analogous Hub 8080 host-network rule too.

After reviewed configuration delivery, confirm the same Broker source can
connect without the correlated PolicyDenied, then validate current Admin
Atlantic API identity, source advertisement TTL 3600, SSA updates/read-back/
cleanup, and another natural grant renewal. Policy apply or Ready alone is
not functional acceptance. Consumer freshness checks and credential lifetime
remain unchanged.
