# Keep the Atlantic bridge distinct from the CN exit

The CN node's GLOBAL proxy selects ATLANTIC, whose existing ExternalName resolves
to among-clusters-gateway. Service frontend1080 previously targeted host1080. On
R640 that socket is owned by mihomos-cn-exit in direct mode. A policy hit named
ATLANTIC therefore did not prove cross-cluster egress: actual GHCR and Actions
connections appeared in the CN exit DIRECT connection table.

20a02b1 introduced the Atlantic1080 import on November20; 8811354 selected it
first in GLOBAL on November21. The later f8ef853 loop bypass did not disable
GLOBAL: effective R640 cn.yaml remains rule mode with GHCR/GitHub rules GLOBAL.
The separate exit.yaml MATCH,DIRECT remains intentional and unchanged. Startup
bind-error logs were not retained in the queried window; endpoint/process and
actual connection ownership are the evidence, rather than an invented log.

Keep the consumer frontend1080 and CN exit1080. Give the authenticated Gateway
import its own31080 listener, named container port, Service target and exact
egress-fabric ingress rule. Existing sessionOnly and Atlantic SPIFFE identity
checks remain mandatory. Public IP/DNS/RouterOS forwards, public authority,
providers, images, Secrets, grants and other imported listeners are unchanged.

The restricted public-authority context was read through authenticated Admin
tooling;31080 was actually unoccupied. The existing six-object
networking-helm-among-clusters-agent-among-clusters owner remains unchanged.
Preserve current Recreate and serialize after active owners. No product build.

After server preview and bounded delivery, verify the Gateway owns31080, the
original CN process still owns1080, and Service frontend1080 maps to31080.
Ready alone is insufficient. A fresh GHCR request through explicit Mihomo must
open an authenticated Atlantic stream instead of a new CN-exit DIRECT
connection. Record complete public blob SHA/size and throughput, preserving
earlier failed/truncated transfers. Do not kill existing connections merely to
improve a measurement. Parent acceptance retains Admin self/Atlantic SSA checks.
