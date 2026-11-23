# Among Hub/Broker telemetry delivery

The existing Hub and credential-broker owners consume the single verified v0.3.36
image `sha256:e4318df4f9f6cc47c391c20f178c4b8000627c69c09cc48364630c4a68853d45`
from Among source `9f57051793c9f5218d1cd0827fa705d54d0bccfd` (product PR101,
release45191613176). Both report release
`among-clusters@9f57051793c9f5218d1cd0827fa705d54d0bccfd`, environment production.
The SDK DSN is the public ingest identifier for Sentry go-http4509349088985088;
no Sentry API token, new Secret, or credential rotation is part of this change.

Use only the existing bounded contracts:

- `networking-helm-among-clusters-hub-among-clusters` (7 objects)
- `networking-helm-among-clusters-hub-credential-broker` (5 objects)

The chart source also updates the compiler-generated kube-system Certificate
contract provenance. Its Certificate payload is unchanged; this is not a request
to deliver that unrelated cohort. Cluster-scoped bootstrap inventory is unchanged.
No Agent/Gateway, authority, HTTP listener, imported route, grant, or lease changes
are included. The onboarding chart/image defaults now match the pinned product.

Metrics use the existing Services' named metrics9090 port, selected by the
observability ServiceScrapes, and bind only DownwardAPI POD_IP (invalid/unspecified
addresses fall back to loopback). The application remains8080. Ordinary Pod
policies select only the observability-system/re8ch vmagent for metrics ingress.
Hub remains hostNetwork: ordinary Pod policies alone do not establish a host
firewall boundary. Runtime acceptance must confirm its actual POD_IP is private
and direct public9090 is unavailable. No wildcard bind or public metrics route is
introduced. Sentry-enabled KNP egress permits IPv4/IPv6 public TCP443; this is an
explicit L4 HTTPS allowance, not FQDN restriction.

Before execution, use server dry-run and review actual managedFields conflicts
against each contract's existing force allowlist. Never force unrelated resources
or change keys/identity configuration. Keep both contract executions serialized by
the existing workflow lock and reuse each signed configuration bundle on retry.
Do not rebuild the product image.

Acceptance requires actual imageIDs, Ready/restarts, private metrics bind and
scrape UP for both existing Services; exact seven RED labels and four build-info
labels; no trace/operation/user/resource labels or unsupported exemplars; JSON
logs correlating trace/operation/event IDs; Sentry event/transaction read-back with
this release and native commit/PR association. A signed release or successful
apply alone is not runtime acceptance. Retest current Admin self and Atlantic
read-only calls after delivery, retaining any first error.
