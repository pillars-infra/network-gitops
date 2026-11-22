# Isolated AF / AmongCluster / PublicEdge acceptance fixtures

Status: **review input only; not deployed or accepted**. No file here is included
by `clusters/re8ch`, a domain kustomization, or the 43-object networking release.
These are individually previewed Admin MCP inputs, not a new controller/planner.

## Actual scope and prerequisites

- Host: `af-canary.service.re8ch.com`. Existing Gateway `kube-system/re8ch-gateway-canary`
  listener `service-wildcard-https` permits this host and namespaces; its Ready Certificate
  `re8ch-service-public-gateway` covers `*.service.re8ch.com`. No Secret is read/changed.
- The base wildcard Certificate `*.re8ch.com` alone does not imply a matching listener;
  this plan adds no listener, public IP, DNAT, route, nameserver or authority change.
- Actual Ready authority Pods currently run on **domain-ex** and **suxunji**, not R640.
  First bind only domain-ex; suxunji must fail closed for the canary until its own ref is bound.
  R640 hosts the backend and is a separate path-observation source, never a forged authority identity.
- Source agent: `among-clusters/among-clusters-agent`, identity `re8ch`, trust domain
  `re8ch.internal`, peering namespace `byoc-pilot`; existing Service get/list covers this
  namespace. The agent polls List and needs no watch or broader Service permissions.
- Existing Peer `byoc-pilot/re8ch-atlantic` is Ready and names re8ch/re8ch-atlantic.
  A new policy authorizes only canary class + HTTP port 8080 + this exact peer, quota one.
  A label alone is insufficient: annotations, existing signed identity and hub policy must all pass.
- Required releases: AmongCluster typed ingress/import fixes, AF TLS collector + dynamic
  advertisement resolution and formal v1alpha2 CRDs, then PublicEdge 0.8.14 consumer.
  Configure PE evidence group `networking.advfab.org`; do not extend legacy schemas.
  New-stream QUIC lease/tombstone validation is a separate prerequisite for claiming QUIC withdrawal.
- Record exact signed source revisions, artifact digests, Pod UIDs/nodes/readiness and auditRefs.
  A green source PR or imported-service Ready status is not end-to-end evidence.

## Apply phases — no bundled apply

1. Through current Admin catalog, preview each `00-foundation.yaml` object separately,
   then apply that exact manifest with its server-issued plan hash. It creates only namespace,
   bounded token-free test server, Service and one HTTPRoute. Service initially has no export label.
   The server has no service-account token, credentials, arbitrary target or database access.
2. Confirm Pod Ready and HTTPRoute Accepted/ResolvedRefs on the existing listener. Capture
   actual Pod/node and Service/route UIDs. No tenant-api or production fault injection is allowed.
3. Merge only the canary leaf from `05-runtime-service.fragment.json` into the live
   `regional-routing/public-edge-runtime` runtime.json, preserving every other key/value.
   First read and retain its resourceVersion/baseline outside Git; construct the full candidate
   ConfigMap, compare the one-leaf change, then preview/apply through Admin MCP. Never replace
   the JSON with this fragment or reset model/routes. `requireFederatedContract` disables fallback.
4. Probe A=223.159.210.222 and B=179.255.126.104 directly with SNI set to the canary hostname.
   Check validated TLS, HTTP 200 and the exact 16384-byte `/transfer` body. B is a proposed relay,
   not assumed healthy for a newly added hostname. If relay policy rejects it, report the actual
   failure and stop this phase; do not patch shared allowlists, public routing or authority.
5. Preview/apply the policy in `01-enable-reviewed-export.yaml`, then the Service document.
   Only that Service gets the export label and reviewed annotation. The agent's signed snapshot
   must create the real advertisement/import; never fabricate either object to claim success.
6. Read actual ad/import UIDs and current revisions. Expect owner re8ch, Service identity
   `spiffe://re8ch.internal/ns/af-canary/service/af-ingress-canary`, protocol http, selected HTTPS
   endpoint primary and current import projection. Validate publication time + TTL and peer target.
7. Preview/apply `02-exact-read-access.yaml`: get-only access to these two exact object names
   for the existing AF/PE service accounts. No Secret, list/watch or write permission is granted.
8. Fill real UIDs in `03-af-target.fragment.yaml.in`; append only this entry to the formal
   AdvancedFabric's networkQuality.amongTlsTargets, preserving all existing targets/settings.
   This is a fragment, not an applyable resource. Preview the full single-object candidate first.
   It resolves the same ad/import endpoint, never a separately hardcoded IP/SNI/path.
9. Collect fresh Service NPA on domain-ex, suxunji and R640, with host+pod and both
   expected sizes [0,2048], matching service/endpoint/source/target scope and latency budget.
   A bound authority needs its own passing evidence; record a failing R640 diagnostic separately,
   never borrow another node or turn one failed source into a global readiness bit.
   Record scope.targetConfigurationDigest; do not compute a different digest.
10. Fill the actual domain-ex NPA UID in `04-publicedge-binding.yaml.in`, then preview/apply
    that one PublicEdge. No unresolved `__...__` marker may be applied. Query actual domain-ex
    authority process and public canary TLS path; record decision/ref revisions and DNS A/TTL.
    Do not claim global authority acceptance while suxunji correctly lacks its own binding.
11. Merge only the suxunji reference from `04b-suxunji-ref.fragment.yaml.in` after its own fresh
    NPA is verified; preview the full PublicEdge. Then verify both authorities independently.
    Neither authority gets a fake NODE_NAME; R640 evidence remains diagnostic for the backend path.

The canary uses area `GLOBAL` to isolate identity, endpoint, evidence and DNS convergence.
It does not validate Geo selection or physical-route reconfiguration. Production relay
candidates retain each site's reviewed RegionalRelay/origin-CN policy; this fixture does
not copy the canary DirectGateway policy onto overseas production endpoints.

## Controlled changes and pass criteria

- Source-only IP move: replace only the Service's reviewed public-ingress annotation with
  `06-primary-moved-to-la1.fragment.json`. PE endpointId stays primary and AF ref stays unchanged.
  A remains healthy as secondary; primary's actual site/region/address/revision move to LA1.
  Observe ad revision → current import → resolved AF target → fresh scoped NPA → new independent
  PE probe → DNS B. Fix the acceptance deadline at **180 seconds** from the source change
  to fresh matching NPA and DNS B; current measured host/pod collection cycles take about
  45–70 seconds. Record a missed deadline as failure, without moving the threshold.
  Old health, in-flight A results, DNS grace and literal fallback must not resurrect A.
- Add/remove/reorder: keep stable IDs; adding/reordering an unselected endpoint cannot reset current
  health. Removing primary while secondary stays healthy must reject that binding, not pick array[0].
- Revoke: restore the unexported Service document from foundation; observe source/hub revocation,
  AF withdrawal and PE/DNS exclusion while test backend stays healthy. For QUIC, prove a **new**
  stream is refused; existing streams retain their explicitly documented policy and are not killed.
- TTL isolation: do not stop the shared source agent, block its control channel, pause the whole
  issuer snapshot or expire other advertisements. Producer IP movement and Service export/revocation
  above must use the real agent chain and cannot be replaced by this consumer-only test.
  For TTL, use `07-consumer-ttl-snapshot.yaml.in`: an explicitly labelled, separate controlled
  advertisement/import UID pair (no publisher identity or credentials are created). It has no
  agent publisher-management label, so it is neither renewed nor removed by the normal snapshot.
  This diagnostic object does not claim to have passed real publisher admission. Late-bind its own
  exact get-only access/ref UIDs, temporarily point only the canary AF/PE refs at it, and keep HTTP
  healthy. Start its five-minute timestamp only immediately before apply. Prove it was eligible
  first; then observe expiry despite stale Active/Ready and prove AF/PE/DNS withdraws.
  This shadow pair does not control the real publisher's QUIC lease: QUIC new-stream denial
  must be verified separately with real source export withdrawal above.
  Record this as **isolated consumer TTL acceptance**, never producer heartbeat-pause acceptance.
  Restore the real producer refs and delete only the diagnostic pair/access objects afterwards.
  If it never becomes eligible or isolation is unavailable, mark the case unexecuted/blocked.
- Body fault: change only canary publicIngress.path to `/stalled-body`. Record headers 200 but failed
  body/latency evidence and ineligible DNS; never inject faults into tools, db-rw or tenant-api.
- Restore source `/transfer` and fresh revisions/evidence before cleanup. Revoke export, remove canary
  PE and runtime leaf, then exact read bindings/policy and foundation resources through preview/delete.
- This fixture is not final production acceptance: real tools metadata/native MCP and db-rw token
  routes must later migrate to their real Service owner/port mapping, then pass real Admin calls.

## Fragment / data handling

Keep raw measurements, ad/import/NPA samples and audit outputs outside Git. Commit only the
reviewed input and stable conclusions. Late-bound UIDs and opaque digests are identifiers, not Secrets.
No fixture modifies shared publication adapters or adds a second reconciliation authority.
The transfer body is 16 KiB: the collector's 32768-byte response cap includes headers,
so a 32 KiB body would be invalid. `verify_collector_contract.py --collector-source <reviewed
conformance-probe.py>` checks this actual server against the actual strict collector function
with an ephemeral local test CA. It is a local contract check, not cluster/host+pod acceptance.
