# PublicEdge 0.8.15 runtime promotion

Use the unique successful upstream release run 45107990105, signed tag v0.8.15 and source 9da078dbb1205b7a057a82891a2d6bda9c5bf99e. Controller image is `sha256:7681129722c6b11a8922b8ee6207e9232ba83bd2a1b4ab1ca6c7a2340356cfb2`; chart OCI is `sha256:b8851656a0a2bfe80be53dfe4fc54d8d3ae799c052516b0ecb5b8286c8f0c1d6`; archive SHA256 is `c13347cf90509db44478b3bf3aa9278e6a976c7a269ea6342f5b48bc7073c42c`.

Before promotion, verify chart and release-manifest Cosign blob bundles, exact workflow/tag/issuer, chart and controller GitHub attestations against this source SHA, all referenced evidence file digests, controller OCI Cosign signature, and byte equality between the OCI chart archive and signed release asset. No product artifact is rebuilt by the GitOps promotion.

Main Agent and gateway 0.3.34 are actually deployed by network release 45107373985; both new Pods are Ready with zero restarts. The 0.8.15 controller provides source Service lease publication. It stays opt-in until a reviewed real local Service export and consumer binding are established. This artifact promotion alone is not IP/Service/DNS convergence acceptance.

Preserve the effective two-node authority placement (`suxunji`, `domain-ex`), `maxUnavailable: 1`, existing public authority topology and required AF evidence group `networking.advfab.org`. Never schedule through authority-health labels or reuse the failed 0.8.11 bundle. Bootstrap the existing controller role's formal AF resource permission before rollout; inspect the complete runtime cohort for unrelated drift. Verify actual image IDs, runtime code, authoritative DNS, real tools/token calls and subsequent source-to-import-to-AF-to-DNS change/expiry behavior.

The release orders configuration before workloads: `envFrom` is read only at process startup. A new Pod checksum alone cannot prove the intended ConfigMap was present when the container started. The same stage order applies to rollback.
