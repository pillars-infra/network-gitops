# R640 current Pod allocations at the RouterOS boundary

The PodCIDR reconciler already derives local origination from Cilium's current
multi-pool allocation and a durable ownership ledger. Its RouterOS export
prefix-list previously permitted only the legacy inventory `podCIDR`, so locally
originated current pools did not reach the RouterOS peer.

The existing `reconcile_routeros_boundary` now delegates the complete exact
`ROS-R640-SERVICE-OUT` prefix-list to the shipped ownership helper. It uses the
same accepted `owned_pod_cidrs` that `apply_fabric` has just reconciled. It does not
query a second registry or hardcode today's allocations. The original declared
service VIP exports remain permitted in a separate sequence range. ASN, peer,
Gateway VIP, provider public IP, next hops and RouterOS configuration are unchanged.

Full replacement of this owner's one prefix-list withdraws retired or reassigned
pool exports. Allocation read failure, a partial/conflicting snapshot, and a
missing Cilium owner reference retain the existing last-known ledger. An explicit
authoritative empty set is distinct from unknown state; a Kubernetes Node UID
change blocks reuse of another node's ledger. A recreated CiliumNode belonging
to the same Kubernetes Node can advance the source UID/resourceVersion normally.
The existing allocation-semantic hash loop automatically reruns reconciliation
on accepted allocation changes, rather than every status heartbeat.

The clear helper validates canonical cluster `/24` prefixes before emitting any
VTY commands. It permits only the cluster's legacy/native Pod pools and declared
service `/32` VIPs. It never touches other FRR prefix-lists. The existing global
origination/retirement ledger remains the authority for BGP networks and Null0
ownership; this patch does not add routes or a second ledger.

The restricted reconciler source changes its old single-prefix render block to
one call to this helper and uses a native fail-fast batch adapter. Both zebra
and bgpd prefix-lists are independently read back; a zero exit with stale
exports is not accepted. Its live non-Secret code was first checked
against the existing authenticated source digest, then resealed using the
repository's existing public age recipient. No local SOPS decryption or Secret
value access was used. Both restricted-code and clear-helper digests are updated,
and the existing DaemonSet code-package revision requests a controlled rollout.

## Acceptance after reviewed delivery

Use the existing signed `networking-native-kube-system` artifact path, including
configuration-before-workload ordering and real server-side preflight. Coordinate
with other network writers; do not change RouterOS filters or add static host
routes by hand. Verify actual mounted code and the R640 process/owned ledger,
then the RouterOS peer's advertised routes and destination-scoped read-only
RouterOS route observations. Preserve the original failed probes.

Finally send one Registry-source query per DNS transport, plus an independent
normal Pod HTTPS/raw-URL read, and correlate the actual return path. Successful
BGP publication alone is not end-to-end recovery. Root's current allocation
contract and public authority inventory remain the boundary for any additional
RouterOS-side change demonstrated by those observations.

Deployment and runtime acceptance are pending this PR's review and delivery.
