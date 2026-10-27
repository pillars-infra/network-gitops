# RE8CH Network GitOps

Public desired-state authority for RE8CH Gateway, DNS, Cilium, and cross-cluster network configuration. Open-source networking products remain in their own organizations.

GitHub Actions builds and signs immutable release artifacts. The bounded SSA
executor applies reviewed contracts and replays accepted digests from the cloud.
Local Flux controllers are retired and must not be restored as a fallback.
Retained Flux resources describe historical inputs; they do not authorize a
second runtime writer. Source publication and successful runtime adoption are
separate facts, verified through workflow results and accepted-state evidence.

## Cilium authority and R640 Gateway recovery

`networking-helm-cilium-kube-system` adopts resources of the existing
`kube-system/cilium` release; it does not install a second release. The vendored chart and every
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
after the fixed operator, R640 agent and real traffic probes succeeded. The cloud
network executor is not authorized to administer arbitrary admission policy.

## Steady-state invariants

- The cloud Cilium contract is the only adoption path for the existing
  `kube-system/cilium` resources; do not start a second Helm/Flux writer.
- The vendored chart and all images are immutable and digest locked.
- Chart versions and archive digests are locked for cloud compilation.
  `rollOutCiliumPods` remains disabled.
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
into protected execute/preflight steps and the fixed Advanced Fabric compiler.
Ordinary publication never receives the key. The executor
verifies the signed bundle, decrypts the ConfigMap in memory before adding audit
annotations (preserving SOPS MAC verification), checks plaintext parity and exact
identity, and sends plaintext only through kubectl stdin. Sensitive stderr and
command failures are redacted. Missing explicit key provisioning fails closed;
runner-local default key discovery is not used. Secret objects remain forbidden.

`dry_run=true` now preflights the same signed artifact and exact inventory through
the executor without changing durable accepted state. Use `mode=publish` for a
new release; `mode=reconcile` requires a previously healthy accepted artifact.

Secret objects, platform-owned bootstrap/RBAC/CRDs, unpinned images and unsupported
cluster network pools remain explicit in the omission ledgers. Encrypted Helm
values use the protected compilation path below. No local Flux writer is needed.

Use `mode=reuse`, `reuse_digest` and `reuse_source_commit` to preflight or accept a
previously published artifact before any accepted state exists. The workflow
verifies the certificate's build SHA and compares the entire current contract and
source closure with that ancestor commit; it never rebuilds in reuse mode.
`mode=reconcile` selects the accepted artifact from durable state instead.

## Cloud Helm rendering

`compile_helm.py` uses the existing pinned chart digests, source HelmRelease
values and Kustomize post-renderers. The lock binds chart archive hashes, Helm
v4.2.3 and the observed Kubernetes capability version. CI verifies cached chart
bytes before reuse and reproduces the reviewed snapshots; reconcile later pulls
the signed compiled OCI artifact without downloading/rendering Helm again.

Four charts (Cilium, PublicEdge, Among Clusters agent/hub) project 47 namespaced
runtime objects into six bounded contracts. `helm-authority.json` holds exact
bootstrap/RBAC manifests separately. Existing Cilium TLS Secrets are preserved,
not regenerated into public artifacts. Hook/one-shot operations are excluded
from periodic reconcile.

Advanced Fabric uses a separate fixed protected compile step for its encrypted
HelmRelease and inventory ConfigMap. It renders the same pinned chart and reviewed
Kustomize overlays, excludes hooks and platform bootstrap resources, and encrypts
22 existing runtime objects before ordinary OCI signing. Only object identities
remain visible; no decrypted resources are uploaded. The executor verifies the
artifact before decrypting and validates the exact identities and image pins.

Initial Advanced Fabric adoption additionally checks the restricted topology
source digest and live spec parity against the SSA resourceVersion precondition.
Any difference or concurrent change blocks adoption; diagnostics expose only
fixed-category counts. This check runs for both server preflight and execution.
After a healthy acceptance, reconcile may repair drift while still validating the
source pin. Exact platform-owned diagnostic RBAC grants only GET on
`ops/restricted-topology-context`.

All native and Helm adoption contracts set `authorization.requireExisting=true`.
The executor fetches each object's resourceVersion and supplies it as an SSA
precondition for both dry-run and apply, including rollback. Missing objects
fail closed; this adoption path cannot recreate a deleted object. Explicit new
resource creation remains a separate publication authority.
