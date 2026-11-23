# Cloud-bound SSA delivery

The network repository executes its own checked-out Python executor. A central
service-backend change does not update that source. This port uses the reviewed
2959 transport, preserving the network repository's protected Helm, SOPS,
redaction, topology parity, protected-kind and per-object resourceVersion guards.
It does not add a service, controller, planner or executor image build.

## Two authorities

The outer workflow always keeps its original **main** kubeconfig for bound
contracts. Its state ConfigMaps live in main/default:

- `ssa-state-networking-native-self-cloud-target-canary`
- `ssa-state-networking-native-atlantic-cloud-target-canary`

Existing networking Actions identity receives only GET/PATCH on those two
state objects. Admin bootstraps missing empty seeds once; if a seed exists,
read and validate it rather than overwrite acceptance data. Seeds are explicit
platform-bootstrap objects, excluded from runtime apply inventory. Self's
business canary additionally grants get/patch/update/delete on only
`default/ConfigMap/re8ch-cloud-target-canary`. No ordinary create or Secret,
impersonation, bind or escalation permission is added.

Inside Executor.command only, a short-lived loopback adapter forwards the
business request. It retains the original Actions proof, release ID and binding
digest, including when API proxying strips Authorization. The selected main
endpoint, public CA and SNI remain one transport; no insecure TLS or user
credential forwarding is allowed. Gzip, response streaming and disconnect
cancellation are preserved. This socket and credential-free kubeconfig exist
only during that command; the outer KUBECONFIG never changes.

Self first resolves its actual ClusterIdentity/API Service UID through Cloud,
then retains the original caller's main RBAC. It creates no fake remote grant.
Atlantic uses only its independent exact-name execution grant. Its business
grant needs no state ConfigMap permissions because state remains in main.
The existing interactive Admin grant is never given to Actions.

## Late binding and all operation paths

The two templates under `operations/releases/conformance-contracts` are
non-executable preparation. No fake UID or binding hash is checked in. After the
actual scoped grant UID and reviewed Cloud configuration digest exist, copy the
template under its canonical contracts name, add the actual clusterBindingDigest
and submit the factual reference through review. Profile/Executor reject a
missing binding for either canary and reject unsupported legacy remote execution
before acquiring credentials; there is no direct-Atlantic fallback or OIDC
configuration change. Both bound targets reuse the existing networking audience,
environment and group.

Preflight, execution and independent observation all bind the same target.
Hydrate, accepted-artifact reuse, reset and state patching reject another target
or binding. Cached results cannot bypass contract/target checks. Existing-only
adoption retains the first observed UID while refreshing resourceVersion per
object; deletion/replacement is rejected. Rollback retains the same UID guard
and fresh version behavior. Reserved object audit annotations are stable release
ID/artifact digest, while per-attempt operation IDs remain in state/results.
Rollback annotations identify the restored artifact, not the failed attempt.

These are explicit manual conformance releases, excluded from scheduled replay.
Record genuine Actions creation/readback and out-of-scope rejection, then audit
cleanup separately and retain durable main evidence. A healthy stub, merged PR,
import Ready or successful publisher is not actual two-target acceptance.

## Current protocol boundary

This adapter supports ordinary HTTP requests and streaming watch/log responses.
It does not yet transparently forward Upgrade/SPDY/WebSocket sessions required
by kubectl exec, attach or port-forward. No new CLI prohibition is introduced;
those operations need a separately implemented and tested upgrade transport.
The current conformance claim is limited to real read/write/SSA and AF APIs.
