# DNS authority admission and recovery

Authoritative DNS admission uses the existing controller’s bounded public SOA
checks for every declared child zone over both UDP and TCP, requiring two of
three replies per transport. A record availability belongs to ServiceEndpoint
and must not retire the authority needed to recover an application.

Globalping continues publishing independent public telemetry. Its measurement
quota, own DNS resolution, and ConfigMap publication do not gate DNS admission:
the observed failure left only zan delegated, and rolling that frontend then
made the API hostname and Admin plugin unreachable. No authority-health label
is used to schedule PublicEdge. The exact node selector and private backend
port remain unchanged. HE stays removed.

The existing chart exposes all necessary configuration. No new product image
is needed. After application, read the parent NS delegation and authoritative
NS/SOA, run the five-region UDP/TCP matrix, and verify actual Admin plugin
operations. A successful Actions apply alone does not satisfy acceptance.
