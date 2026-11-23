# Self-cluster metadata binding

The Cloud target resolver binds self/re8ch through the same reviewed cluster
binding model as remote targets. It uses the existing ClusterIdentity and
Kubernetes Service UIDs; it does not register a new identity or manufacture a
new grant. Local transport is only an implementation detail after resolution,
authorization, plan binding and audit.

The actual Cloud ServiceAccount initially lacked both exact metadata reads.
Extend the existing byoc-pilot metadata Role with GET on ClusterIdentity/re8ch.
A separate default namespace Role grants only GET on Service/kubernetes, bound
to the same ai-operations/re8ch-cloud-platform ServiceAccount. Neither Role
grants list/watch, Secret access, token issuance or global review permissions.
RBAC is platform bootstrap and is excluded from runtime release bundles. Apply
these reviewed objects through native dry-run/plan, then verify both exact
SelfSubjectAccessReview results before accepting the new Cloud runtime.
