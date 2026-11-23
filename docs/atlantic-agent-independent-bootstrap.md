# Independent Atlantic credential-producer recovery

The existing Admin broker credential stopped renewing on 2026-11-21: the
reviewed grant remains approved through 2027, while broker metadata declares
the last uploaded credential expired at 2026-11-21T16:39:39Z. The outbound
Atlantic identity still advances its Hub generation and publishes services.
A successful heartbeat is therefore not evidence of credential renewal.

Cloud's target binding correctly fails closed on the expired broker payload.
This also prevents updating the remote producer through that same broker.
The native gap is recovery of that producer without exporting credentials or
giving the main release executor an Admin wildcard grant.

Only the existing `networking-native-atlantic-among-clusters` contract may use
its original independent `release-executor-networking-atlantic` environment
and audience. Its existing namespaced Role grants get/patch on exact Agent,
gateway, edge, approval and durable-state objects. No RBAC, OIDC configuration,
secret, grant or target endpoint changes are introduced here. Existing-only
application and no-prune are mandatory. Other unbound remote contracts remain
rejected, and the independent path remains excluded from automatic replay.

First run the existing workflow with execute=false and dry_run=true. Preserve
the current Agent identity/configuration and server authorization evidence.
The exact Deployment GET publishes only its UID/generation and boolean
comparisons against reviewed image, cluster identity, broker endpoint and
sync interval; environment values and credential references are not logged.
Preserve the separate observation artifact even if state hydration fails,
and compare intended changes against the reviewed 0.3.34 image-only promotion.
Then reuse that immutable bundle for bounded application. Observe the original
grant UID and credential expiry advance through natural Agent polling; do not
patch the TTL or reset the grant. If it does not advance, retain the failure
and diagnose the upload path rather than declaring an image change sufficient.

Recovery is complete only after the same current Admin plugin can read the
Atlantic API identity, perform SSA revision 1 and 2 with read-back, and clean up
the reviewed conformance object. The independent Actions application is not a
substitute for those BYOC acceptance checks.
