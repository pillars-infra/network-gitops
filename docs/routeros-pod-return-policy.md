# R640 Pod return policy

The existing public-forward controller owns this repair. Public authority remains
provider `223.159.210.222` → RouterOS → `10.251.0.4`; the peer, VIP exports,
legacy rules, NAT declarations and credentials are unchanged.

On 2026-11-23, R640 advertised its accepted Cilium-owned allocations, including
the current tenant pools. RouterOS still admitted only legacy `10.42.6.0/24`
and the VIP, and its service-table lookup rules covered only the legacy range.
Registry Pod public-DNS requests reached the remote authority and received a
reply there, but no reply reached R640. Host-origin queries succeeded. These are
diagnostic facts; source changes alone do not prove recovery.

`podReturnPolicy.poolRefs` references the existing four `CiliumPodIPPool`
declarations. The native compiler projects their aggregate CIDRs and `/24`
allocation size into the existing ConfigMap JSON. This small projection fills
Kustomize's inability to copy structured object fields into JSON-valued data;
it adds no IPAM registry or controller. The static Kustomize and signed native
views are checked for parity. Current node allocations are not duplicated here:
R640's existing owned-ledger export controls which assigned prefixes are offered.

The provider first validates the exact existing peer, chain, table and ordering
anchors. It creates only explicitly commented `/24` aggregate admission rules
before the existing reject and `lookup` rules before the legacy lookup anchor.
It replaces/removes only its own comments, preserves fallback and foreign rules,
and requests an exact established session's IPv4 soft route refresh after import
changes. Missing identity, ambiguous ownership or invalid pools fails before
network writes. Converged policy performs no writes or refresh.
An unsuccessful refresh remains pending until an exact fresh session accepts it;
the next loop refreshes without replaying installed configuration. A new process
performs one validated refresh to cover interruption after configuration writes.
The installed RouterOS rejects the newer `address-family` REST argument. Refresh
therefore requires both observed session AFIs to be exactly `ip`, then sends only
the exact session identity. Missing, mixed or non-IPv4 families fail closed; this
is not a runtime fallback to an unscoped refresh.

The existing five-object native contract installs configuration before runtime.
A code hash on the existing Deployment forces its startup-loaded Python modules
to reload. Capacity remains the reviewed 256 MiB request / 2 GiB limit.

Acceptance requires the new process/code hash, unchanged peer identity, correct
rule ordering, RouterOS active installed allocated routes, and real Registry Pod
UDP/TCP public-DNS replies. A successful release or R640 advertisement alone is
insufficient. Preserve previous failures and distinguish Pod from host sources.

RouterOS references: [REST API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API),
[BGP](https://help.mikrotik.com/docs/spaces/ROS/pages/331612228/routing+bgp),
[policy routing](https://help.mikrotik.com/docs/spaces/ROS/pages/59965508/Policy+Routing).
An empty REST `fib` flag is also returned for `main`; it is not evidence that a
table is disabled. This repair does not change table flags or use lookup-only.
