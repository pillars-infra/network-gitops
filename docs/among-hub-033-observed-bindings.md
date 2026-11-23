# Among Hub 0.3.33 observed binding promotion

Promote the already built, signed release from source
`d887586f58530697ef8769b92cf31167a1921647`, successful run `45085399266`.
Do not rebuild it or wait for a later Agent feature release.

- Unified image: `sha256:dfec9b42b6f9ebcb67228b5c50fff83c75069da8da40ae9ffd88c8990cfd70c7`.
- Hub chart OCI: `sha256:a9cea5fe8143eca8c325e9bb192f42c124756d93ab0246bb3c0d775d3997702b`.
- Hub chart archive SHA256: `b05f6e1fd24530f5933a9526055b4f5c6f691b721d4c96d65579bd9dfaa6959e`.

Image and chart Cosign identities are the exact release workflow at
`refs/tags/v0.3.33` with GitHub OIDC issuer. Both architecture attestations,
provenance source and SBOM blobs were independently verified through the signed
image index. The OCI Hub chart payload equals the existing release asset byte
for byte. The Hub image override is named and explicit: existing broker and
Agent image values are retained. Only the existing Hub namespace runtime cohort
is published in this step.

## Schema and caller prerequisites

The observed live ImportedService CRD status schema declares only reason,
serviceRef and state and prunes unknown fields. Upgrade its reviewed additive
schema properties before expecting observedGeneration, advertisement UID and
generation/resourceVersion, publicIngress and expiry to survive status updates.
Desired CRDs remain in the generated chart platformBootstrap ledger; they do
not enter a runtime executor bundle. Use current UID/resourceVersion tests and
only additive properties from this exact signed chart when bootstrapping the
existing CRDs. Do not erase older schema fields, versions or ownership.

The observed Atlantic Kubernetes import is Failed and lacks observation fields;
it is not a healthy connection. After bootstrap and Hub rollout, inspect its
actual reason and convergence. Do not force Ready or synthesize metadata.

The actual Cloud ServiceAccount also lacks GET on the exact advertisement,
import and peer objects needed by the resolver. The existing namespaced Role
adds only these named metadata reads. Grant `use` remains limited to the one
interactive platform grant; no Actions identity receives that administrative
grant. A separate release execution grant must preserve explicit resourceNames
through a supporting Hub/Agent version before Actions can use it.

The observed Cloud Pods do not currently mount a ServiceAccount token. Their
product publisher must provide a dedicated read-only projected identity/CA
mount; do not reuse a mounted stronger kubeconfig or export opaque credentials.
Network/RBAC success alone does not prove the actual remote API or PE/AF
installation. Verify from the actual Cloud identity after all prerequisites.
