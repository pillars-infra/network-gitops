# Atlantic import bridge ownership

The existing `byoc-pilot/re8ch-atlantic-default-kubernetes-re8ch-atlantic`
Service is the reviewed ExternalName bridge to the existing Among gateway
Service. It has no ClusterIP. Its actual spec matches the checked-in bootstrap
source, but lacks the existing ImportedService ownership label. Hub 0.3.33
therefore observes the advertisement while rejecting this same-name result.

Exclude this exact bridge from native SSA inventory as a
`controller-owned-runtime-result`, retaining its bootstrap declaration as
reviewable migration evidence. Validate the exact ExternalName source before
exclusion. The previous and new cohort both use `prune: false` and an empty
deletion allowlist; the executor returns before pruning when prune is false.
This handoff does not delete or recreate the Service. A newly compiled cohort
also removes the name from static apply permissions and force-conflict scope.
Do not re-execute an older immutable cohort to reclaim this result.

After this PR merges, use a native server dry-run of an exact JSON patch with
current Service UID/resourceVersion and full spec tests. Verify the current
ImportedService UID, advertisement UID/generation and managed bridge spec;
add the existing import label, managed-by label and same-namespace
ImportedService controller ownerReference only. Preserve the complete Service
spec, UID and DNS name. No grant, credential or cluster-wide access changes are
part of this operation. Read back the import state and actual authenticated
remote `/version`; an import Ready state alone is not remote API acceptance.
