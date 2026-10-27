# RE8CH Network GitOps

Private desired-state authority for RE8CH Gateway, DNS, Cilium, and cross-cluster network configuration. Open-source networking products remain in their own organizations.

This repository is reconciled by the autonomous controller stack in
`flux-network-system`. Main Flux owns the controller lifecycle, Flux CRDs and
bounded bootstrap RBAC; it does not own this repository's Source,
Kustomization, Helm releases or runtime inventory. A main Flux failure must not
stop Network Flux from fetching and applying a signed Network GitOps revision.

## Cilium authority and R640 Gateway recovery

`flux-network-system/cilium` adopts the existing `kube-system/cilium` Helm
release; it does not install a second release. The vendored chart and every
runtime image are digest locked. Cilium CRDs remain owned by the main platform
guardrail.

The R640 recovery completed in two reviewed stages:

1. Upgrade only the Cilium operator to the deterministic HTTPRoute ordering
   commit, keep the agent image unchanged, and move R640 from iptables
   masquerading to eBPF masquerading while retaining native XDP.
2. Restart only the R640 Cilium pod, verify Gateway/CEC stability and both the
   VIP and public endpoint, then remove the temporary proxy-return iptables
   guard after eBPF masquerading became authoritative.

The `cilium-gateway-cec-update-freeze` admission policy is not part of desired
state. The freeze and the temporary proxy-return iptables guard were deleted
after the fixed operator, R640 agent and real traffic probes succeeded. Network
Flux is deliberately not authorized to administer arbitrary admission policy.

## Steady-state invariants

- `flux-network-system/cilium` is the only GitOps owner of the existing
  `kube-system/cilium` Helm release; no second release may be installed.
- The vendored chart and all images are immutable and digest locked.
- Helm chart reconciliation follows `ChartVersion`, not every repository
  revision, and `rollOutCiliumPods` remains disabled.
- An offline worker does not fail or roll back an otherwise converged Cilium
  upgrade. Per-node health is monitored separately.
- R640 retains native XDP and eBPF masquerading on `eno2np1`. Its
  CiliumNodeConfig explicitly clears the inherited legacy
  `egress-masquerade-interfaces` value.
- `Gateway Programmed=True` is not a traffic probe. Acceptance requires stable
  CEC content plus TLS/HTTP checks through both `10.251.0.4` and the public
  authority `223.159.210.222`.
- Emergency live controls must either become reviewed desired state or be
  removed after recovery. They may not become permanent out-of-band patches.

The incident evidence, commands and ownership decisions are recorded in
[`docs/r640-cilium-gateway-recovery-2026-10-19.md`](docs/r640-cilium-gateway-recovery-2026-10-19.md).

## Cloud native release execution

`operations/releases/compile_native.py` projects the existing Kustomize root into
27 namespace-scoped ReleaseContracts. Regenerate after desired-state edits and
run `--check` in CI. `native-authority.json` contains exact inventories, bounded
get/patch RBAC and empty state ConfigMaps for the central bootstrap owner.
Adoption does not grant create/delete and pruning is disabled. Role and
RoleBinding objects remain platform-owned under `platformBootstrap`; this
executor receives no bind/escalate privilege.

The `static-release` workflow reuses the service-backend SSA bundle/executor and
the accepted-digest replay port in agent-gitops at commit
`29bbf035b9aa1f8069becf526e7de8d73e095727`. Publish once with `mode=publish`,
then use `mode=reconcile` to verify and replay the accepted immutable digest.
`force_takeover` is restricted to the exact contract inventory; stop the previous
Flux writer before adoption. Protected environment approval, signed provenance,
server dry-run, durable state and optimistic concurrency remain enforced.

Eight SOPS ConfigMaps are included as ciphertext. `SOPS_AGE_KEY` is provisioned
only into the protected execute/preflight step, never the publisher. The executor
verifies the signed bundle, decrypts the ConfigMap in memory before adding audit
annotations (preserving SOPS MAC verification), checks plaintext parity and exact
identity, and sends plaintext only through kubectl stdin. Sensitive stderr and
command failures are redacted. Missing explicit key provisioning fails closed;
runner-local default key discovery is not used. Secret objects remain forbidden.

`dry_run=true` now preflights the same signed artifact and exact inventory through
the executor without changing durable accepted state. Use `mode=publish` for a
new release; `mode=reconcile` requires a previously healthy accepted artifact.

Secrets, encrypted Helm values, Flux metadata, Helm rendering, unpinned images and
cluster network pools remain explicit in the omission ledger. This does not
claim full Helm or Secret adoption and does not restart a Flux controller.
