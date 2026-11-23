# Cloud to Among broker principal migration

The observed Cloud runtime consists of two `ai-operations` Pods with
`app=re8ch-cloud-platform` and ServiceAccount `re8ch-cloud-platform`. The old
broker ingress selected `app=cloud-platform-tool`, which matches no current
Cloud Pod. This change migrates both pre-existing ingress policy objects to
the exact current app and namespace on broker TCP/8080. It adds no namespace-wide
allow and preserves the other broker ingress and egress declarations.

## Existing grant and ownership evidence

The existing `byoc-pilot/re8ch-atlantic-headlamp-admin` ManagedAccessGrant is
approved, active, not revoked, scoped to Cluster, and expires at
`2027-11-20T23:59:59Z`. Its existing rules are `apiGroups/resources/verbs=*`.
Its peer is `re8ch-atlantic`, advertisement is
`re8ch-atlantic-default-kubernetes`, and reviewed UID is
`d9fae24e-cea9-4014-8c93-0837bd8e7e60`.

Live spec matches the canonical declaration in `clusters/re8ch/resources.yaml`.
Its delivery annotation identifies `networking-native-byoc-pilot`; the existing
Atlantic platform bootstrap also includes the same grant approval ConfigMap.
This is the existing managed platform/Headlamp administrative channel, not a
new tenant application grant. `byoc-pilot` is its peering isolation namespace;
it must not be equated with a SaaS organization. The CR has no organizationRef
or tenant application ownerRef. Its historical Headlamp name does not replace
these explicit source, peer, approval, UID and expiry checks.

The namespaced bootstrap Role permits `get` and `use` of that one existing
grant, plus `get` of its exact reviewed advertisement, import and peer objects,
bound only to the actual Cloud ServiceAccount. It grants no list/watch or
unrelated-object read. `get` is needed for the
caller to validate current UID, approval, revocation, expiry and peer before
using the broker. The UID annotation records the reviewed object; Kubernetes
RBAC itself binds names, not UIDs. Cloud target binding must check the UID and
must not treat a replacement same-name grant as equivalent. No new grant,
Secret access, cluster-wide `use`, grant mutation, or RBAC management permission
is given to Cloud.

## Delivery and verification

Roles/RoleBindings remain platform-bootstrap objects. The existing native
credential-broker executor cohort adopts only the two already existing policy
objects, plus its unchanged three egress policies. Its generated executor rules
add only scoped `get/patch` for those policy names, reusing the existing state
ConfigMap and identity; no bind/escalate permission is requested.

After signed PR/CI review, apply the exact bootstrap Role and RoleBinding and
the reviewed executor role delta through the existing authenticated platform
preview/apply path. Then publish the existing native cohort through the bounded
signed release workflow. Do not use a local credential export or direct opaque
credential reference to bypass the broker's caller authorization.

Verify from an actual Cloud Pod using its own mounted identity: broker health,
then the named grant's remote `/version` and bounded deployment/daemonset
metadata reads. The broker performs local TokenReview and exact-grant SAR `use`;
the caller's token stays inside that request path. Preserve the current grant
UID and opaque references inside the backend. Do not export either token or
opaque credential reference. Network admission alone is not authorization, and
neither grant state nor a successful release proves Atlantic PE/AF installation
or cross-cluster runtime conformance.
