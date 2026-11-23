# Atlantic scoped release canary

This release channel is separate from the interactive Admin grant. The existing
networking Actions principal may use only the new namespaced grant for
`default/ConfigMap/re8ch-cloud-target-canary` with get/patch/update/delete. No
ordinary create, wildcard resource or namespace-wide rule is granted. The
Actions principal reuses the existing networking OIDC audience and group;
there is no authentication configuration change.

Cloud may GET the exact execution grant metadata; broker checks the original
verified caller against exact grant use. The API Service proxy Role names only
`re8ch-cloud-platform:19443`, with native HTTP verbs required for the relay.
It grants neither Pod nor Node proxy access. Confirm actual SAR attributes for
this Service URL before enabling the execution binding.

Bootstrap the final 0.3.34 resourceNames schema and Hub, then the remote Agent,
before creating the named grant. Preview/apply this exact new grant, read its
actual UID/generation, and bind that UID in the reviewed Cloud execution
binding. Do not replace the interactive grant or infer a UID from its name.
The owner-side approval ConfigMap approves only generation 1 of this grant;
if the actual generation differs, review that difference before approval.
New objects need reviewed native bootstrap before existing-only cohort apply.
Never publish the entire older Atlantic cohort without a live desired diff.

The initial remote canary is only the named ConfigMap. Keep its creation,
readback, update and cleanup results and first failures. A healthy import or
release success does not prove remote authorization or API execution.
