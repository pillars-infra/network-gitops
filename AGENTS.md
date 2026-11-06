# Network GitOps repository

- Use signed commits and pull requests for every desired-state change.
- Never commit credentials or decrypted SOPS material.
- Pin images and OCI/Helm artifacts by digest.
- The production root is `clusters/re8ch`.
- Read the service-backend public network authority inventory before changing R640 delivery.
- Build, publish and reconcile through the existing cloud SSA workflow and immutable artifacts.
- Local Flux controllers are retired. Retained Flux manifests are inputs, not permission to restore a writer.
- Verify real accepted state or server preflight; a merged PR alone is not runtime adoption evidence.

- Before using RE8CH self-service or platform tools, read [docs/RE8CH-TOOLS.md](docs/RE8CH-TOOLS.md) and discover the current authenticated catalog.

## Shared developer context

- This repository is the desired-state authority for its own domain. The
  [service-backend developer-context declaration](https://github.com/re8ch/service-backend/blob/main/workspace/developer-context.yaml)
  supplies cross-repository navigation only and never overrides this file.
- Start every change from current `origin/main` in a task-specific `codex/*`
  worktree. Keep the base checkout clean; preserve dirty work before cleanup.
- A Codespace is an ephemeral developer machine, not a reconciliation
  controller. GitHub Actions and runtime read-back remain delivery evidence.
- Wiki, Projects and Gists are projections or task evidence. Stable context and
  desired state must be reviewed in Git; never place credentials in them.
