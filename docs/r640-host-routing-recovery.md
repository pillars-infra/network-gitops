# R640 external L3 egress recovery

The R640-only `r640-xdp-native` CiliumNodeConfig selects the supported host-stack
routing mode. It avoids the BPF FIB forwarding path that can reject a full-MTU
packet when a veth Ethernet header is counted against an external L3 device's
MTU. The transit MTU, TCP MSS, routes, addresses, XDP acceleration, service load
balancing and BPF masquerade configuration are preserved. This is a scoped
recovery mode with a host-routing performance cost and a changed netfilter path,
not a claim that the upstream bug has been fixed.

Official references:

- [Host-routing configuration](https://docs.cilium.io/en/stable/operations/performance/tuning/#ebpf-host-routing)
- [Per-node configuration and activation](https://docs.cilium.io/en/stable/configuration/per-node-config/)
- [Matching L3-device FIB length issue](https://github.com/cilium/cilium/issues/49915)
- [Original veth issue](https://github.com/cilium/cilium/issues/39740)

The current upstream report remains closed without a fix. The open
[GSO/XDP FIB change](https://github.com/cilium/cilium/pull/49791) retains zero
`tot_len` for skb lookups and does not fix this case. Changing versions alone is
not evidence of a repair; setting an aggregate GSO packet length would introduce
another forwarding regression.

## Delivery and activation

The desired object is `clusters/re8ch/r640-cilium-datapath.yaml`. The existing
`networking-native-kube-system` contract delivers its deterministic projection
in `releases/networking-native-kube-system/resources.yaml`. No Cilium image,
Helm release, API authorization, or additional runtime writer is introduced.

A CiliumNodeConfig change is not automatically active. After reviewed cloud SSA
delivery, a separately authorized, controlled operation must recreate only the
Cilium agent Pod selected by `k8s-app=cilium` and `spec.nodeName=r640`. Verify the
Pod's node, UID and DaemonSet owner immediately before that operation. The new
agent's config resolver loads the existing node configuration. Do not perform a
cluster-wide DaemonSet rollout or treat a successful SSA apply as activation.
The native release identity does not gain Pod deletion, exec or additional RBAC;
the release coordinator must select the existing approved restart mechanism.

## Runtime acceptance

1. Confirm the replacement R640 agent is Ready and reports host routing through
   the Linux stack; confirm other nodes retain their prior mode.
2. Repeat the unchanged default-MSS application-network API probe and collect
   its matching Cilium drop events. Require no `FIB lookup failed` extended code
   8 for the test flows; preserve any first failed attempt. Smaller-MSS success
   is diagnostic comparison, not an acceptance substitute.
3. Check ClusterIP API access, public Gateway/NodePort service forwarding,
   expected source IP/SNAT behavior, and policy enforcement. Verify the new
   host netfilter path does not change policy or NAT behavior unexpectedly.
4. Confirm native XDP configuration and service VIP behavior remain effective;
   validate application login/token endpoints and real Admin tool calls.
5. Repeat actual cold module calls and calls after the credential-rotation
   window. Keep independent SYN loss at the remote API endpoint separate from
   the R640 FIB drop; correcting one does not prove the other is fixed.

If activation or these checks fail, revert the one node-config option through a
reviewed PR and use the same controlled one-node agent replacement mechanism.
Do not introduce MSS clamping, an ad-hoc route, or a direct host-network write.
