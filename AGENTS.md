# Network GitOps repository

- Use signed commits and pull requests for every desired-state change.
- Never commit credentials or decrypted SOPS material.
- Pin images and OCI/Helm artifacts by digest.
- The production root is `clusters/re8ch`.
- Read the service-backend public network authority inventory before changing R640 delivery.
- Build, publish and reconcile through the existing cloud SSA workflow and immutable artifacts.
- Local Flux controllers are retired. Retained Flux manifests are inputs, not permission to restore a writer.
- Verify real accepted state or server preflight; a merged PR alone is not runtime adoption evidence.
