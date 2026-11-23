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

The change reuses the verified rc16 artifact and existing signed SSA release.
It changes only reviewed target configuration and does not rebuild AF.
