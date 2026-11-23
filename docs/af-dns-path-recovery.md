# AF DNS path recovery

Harbor registry layer commits returned HTTP 500 because the registry Pod could
not resolve its configured OSS storage hostname through AF DNS. Storage had
228 GiB available with no inode exhaustion. The bucket name, storage credentials,
DNS Service identity/address and forwarders are not changed.

At 2026-11-23 02:48 UTC, a single-query matrix from the actual registry network
namespace found:

| DNS destination | UDP | TCP |
| --- | --- | --- |
| AF DNS Service | timeout >5 s | 3.137 s |
| AMD backend | timeout >5 s | timeout >5 s |
| A1 backend | timeout >5 s | 3.155 s |
| B1 backend | 49 ms | 81 ms |
| R640 backend | 29 ms | 24 ms |

The EndpointSlice and Cilium Service map agreed. The A1/AMD processes answered
the same query locally in 27–36 ms and reached their first recursive upstream
in 28–29 ms, locating the observed fault in cross-node Pod paths rather than
the DNS forwarder or image publisher. Pod Ready alone did not qualify that path.

Retain four replicas and a three-replica disruption budget. Place them on the
two nodes with verified registry-to-DNS paths, using preferred anti-affinity
and the existing topology spread to balance two processes per node. This is
temporary availability recovery while A1/AMD routing is repaired and verified;
it does not claim four independent node failure domains or fix those paths.

Use the ordered signed AF delivery contract. Verify four current Ready Pods,
only qualified backend nodes, repeated UDP/TCP answers from the registry,
and successful real Harbor upload commits. Restore four-node placement after
the same cross-node matrix passes. Runtime observations remain outside Git.
