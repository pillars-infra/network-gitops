# Service observation baseline

The existing AF host and pod collectors measure the actual tenant-api OAuth
metadata endpoint through the declared R640 public authority. The three source
nodes remain separate evidence subjects; both request sizes must pass strict TLS
and HTTP 200 within the existing one-second service latency budget. A successful
metadata response proves this public path, not an authenticated Admin operation.

This target is observation-only (`required: false`): it does not elect a DNS
authority, change routes, authorize a remote cluster or gate all fabric health.
Its fixed public address deliberately provides an origin baseline. It is not
AmongCluster endpoint discovery or evidence of automatic address convergence.
The dynamic advertisement/import acceptance remains a separate required test.

Before this change, the live AdvancedFabric (UID
`1d82a19c-bdf9-405b-a715-8e87885a91b5`, generation 25) had empty static and dynamic
TLS target lists, and the Service observation API returned no subjects. After
deployment, verify fresh Service NPA from host and pod on each source, including
the actual Service subject, target configuration digest, timestamps and failures.
Read the same observations through the managed BYOC tool paths; an empty list,
stale evidence or unavailable source does not count as passing acceptance.

The initial target change reused the verified rc16 artifact and existing signed
SSA release without rebuilding AF.

## Collector resources

The first actual measurements exposed collector throttling: both conformance
containers had a hard-coded 100m CPU ceiling. R640's pod collector recorded
193 throttled periods out of 464 and 12.686 seconds of throttling. One complete
HTTP 200 transfer took 1135 ms, exceeding the existing 1000 ms budget. That
failure is retained; the latency budget is not relaxed. The reported connect
duration currently also includes local TLS-context initialization and must not
be treated as a pure TCP handshake measurement or proof of packet loss.

The existing Helm post-renderer now reserves 100m CPU and 64 MiB per collector,
with burst capacity of two CPUs and 256 MiB. Observed average CPU consumption
was approximately 50m; this reserves twice that average and permits the two
TLS workers to initialize without a 100m quota. Only the host/pod conformance
containers change; the verified rc16 artifact is reused. Confirm actual
resources, fresh complete evidence and cgroup throttling after rollout rather
than assuming the resource change alone passes acceptance.

Actual post-rollout evidence at 2026-11-23 02:02 UTC covered all three sources,
both planes and both sizes: twelve strict TLS/HTTP 200 transfers, 32–387 ms,
all three Service assessments Ready under the unchanged 1000 ms budget. The
new R640 collector had zero throttled periods in the sampled cgroup window.
This is origin-path evidence, not yet authenticated BYOC consumption or address
convergence acceptance.

## Independent observation windows

Actual generic snapshots also took 160.671 seconds with twenty two-second
samples, followed by a 30-second interval. Serial current-path, alternative-path,
DNS and DoH windows can therefore miss the fixed 180-second convergence budget.
The verified rc17 chart runs these four independent windows concurrently and
still refreshes the dynamic Service TLS plan afterwards. Samples, timeouts and
the service latency/convergence thresholds stay unchanged. It also separates
local TLS preparation from TCP connect timing while keeping both in totalMs.

Rc17 supplies the same collector resource values through its public configuration,
so its deployment removes the temporary post-render resource patches. Verify
actual post-deployment cycle duration and execute controlled Service/address
changes before claiming automatic convergence.

## Configuration precedes processes

The first rc17 delivery exposed a second runtime boundary: the default single
stage sorted workload identities before ConfigMaps. Some DaemonSet templates
received the new source checksum while their mounted runtime ConfigMap still
contained rc16 code. Pod Ready and template checksum alone therefore did not
prove new code execution; the actual process still emitted no preparationMs
and retained a 163-second cycle.

The AF contract now explicitly orders configuration, certificates and fabric
intent before workloads. Automatic rollback follows the same declared ordering.
The earlier failed configuration bundle is not used for forward deployment;
this contract change requires a new signed configuration bundle, while the
verified rc17 product artifact is reused. After complete application, confirm
the actual mounted source hash. Existing Pods already carrying the new template
checksum may still need one audited stateless rebuild after the correct source
is present; verify new process output and measured cycle duration afterwards.
