# PublicEdge 0.8.12 artifact bootstrap

The reviewed 0.8.12 runtime bundle is applied, but the authority pods on
`suxunji` and `domain-ex` are unable to finish pulling their exact GHCR digest.
The suxunji event reports an incomplete layer (`unexpected EOF`). The existing
GHCR mirror depends on PublicEdge; the platform SSH broker has no Ready binding.

This is a bounded recovery procedure, not another runtime owner. The two
nonprivileged, token-free Pods only populate the node image cache with the
already signed release digest and immediately exit. They do not select the
PublicEdge Service, open listeners, mount host paths, or modify node config.
Do not include these objects in the continuous production root.

The explicit TLS port `ghcr.io:443` is a separate containerd registry-host
namespace from `ghcr.io`, so a host-specific GHCR mirror does not intercept it.
TLS verification remains enabled. Verify the manifest digest is exactly
`sha256:c2f23e8364261c6a4aa21430d2795a89719a706ce91daf9cd98d658ddae290e4`
before use. No image is rebuilt, copied or retagged. This temporary cache warmup
does not fix the long-term registry bootstrap architecture.

After this signed PR is merged, use the platform resource apply preview on each
complete Pod object, inspect the plan, and apply the exact returned planHash.
Observe completion and the original authority Pods' pinned image readiness.
Delete the two recovery Pods through preview/delete after collecting evidence,
or after their deadline if pulling remains unsuccessful. Keep all release
references unchanged; never restore authority-health placement.

References:
- Product release: https://github.com/public-edge/public-edge-manager/actions/runs/45028012460
- GitOps source: https://github.com/pillars-infra/network-gitops/pull/202
- Applied bundle: `sha256:55390bfdbd08b31f25281453cd4c80997935931c17fa3b25300f42f7a9b2e00d`
- containerd host namespaces: https://github.com/containerd/containerd/blob/main/docs/hosts.md#port-handling-in-registry-host
