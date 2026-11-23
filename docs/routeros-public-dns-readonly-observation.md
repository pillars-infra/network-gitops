# RouterOS public DNS return-path observation

This change adds an on-demand, GET-only diagnostic to the existing
`ops/routeros-public-forward-controller` ConfigMap. It does not enable the
retired `kube-system/routeros-node-controller`, install a second observer, or
change RouterOS desired routes, NAT, the public authority, or controller startup.
The pinned Python image and current mounted `mikrotik-routeros-admin` reference
remain the existing provider adapter's responsibility. No credentials enter Git
or diagnostic output.

The legacy RouterOSNode status dated 2026-10-03 is not current observation:
its controller is deliberately at zero replicas and the old object no longer
contains the old code's required fields. The running public-forward and transit
controllers are the current provider owners. Reuse their access boundary rather
than scale the legacy process or invent ASN/peer declarations.

## Scope and meaning

`/config/observe.py` imports the existing guarded `reconcile.Router` adapter,
then issues exactly three HTTP GETs: route facts, NAT facts, and one exact UDP
connection tuple. Source addresses are restricted to the reviewed R640
`10.68.9.0/24` allocation; destination addresses are the three currently
published public DNS authorities. A nonprivileged source port is mandatory.
An address outside that scope fails before constructing the adapter.

The output contains only allowlisted scalar fields. It excludes comments,
credentials and unrelated connection entries, even if the provider ignores
query filters. NAT candidates retain their RouterOS order; unknown/inverted
selectors remain explicitly unknown. Candidate rules are not packet-hit proof.
An absent or expired connection is reported as such and never triggers a retry,
probe, repair or business replay. The helper has no health gate or mutation path.

## Reviewed delivery and actual verification

1. Review and merge this signed PR after render, policy and tests succeed.
2. Deliver only this ConfigMap through the existing signed GitOps/static-release
   path. Keep its existing desired.json and reconcile.py unchanged. Inspect the
   server-side preview before applying the same reviewed object. This PR does
   not authorize applying the entire network root or restarting either owner.
3. Wait for the existing mounted ConfigMap to refresh, and compare the SHA-256
   of `/config/observe.py` with the reviewed rendered value. No image rebuild or
   process restart is needed: the helper is a separate on-demand command.
4. Through the currently authorized Admin Kubernetes exec tool, invoke the helper
   in the current public-forward Pod, for example:

   ```text
   python3 /config/observe.py --source-address 10.68.9.236 --destination-address 101.34.217.95 --source-port 44482
   ```

   Use an actual, current source tuple, not an expired historical connection.
   Record UTC and the operation/audit reference. Retain only the allowlisted
   diagnostic result outside Git. Coordinate a single DNS probe and header-only
   capture if a current connection entry is needed; the helper emits no probe.
5. Match observations to the already recorded packet path before proposing any
   network change. A route candidate does not establish the active FIB, and an
   emitted cloud reply does not uniquely locate a later drop at RouterOS.

Existing recovery facts: both PublicEdge authorities were verified on 0.8.15;
public-host cross-authority DNS worked, and R640 host queries worked. A Registry
Pod query reached the public authority and elicited a reply, but that reply was
not observed entering R640. Those facts narrow a source-specific return path;
they do not justify a blind hairpin-NAT or host-route change.

Deployment and a live invocation of this new helper remain pending review.
