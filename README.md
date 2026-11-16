# RE8CH Network GitOps

<!-- gitops-status:start -->
[![Reconcile](https://github.com/pillars-infra/network-gitops/actions/workflows/networking-reconcile.yml/badge.svg?branch=main)](https://github.com/pillars-infra/network-gitops/actions/workflows/networking-reconcile.yml?query=branch%3Amain)
[![Contract validation](https://github.com/pillars-infra/network-gitops/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/pillars-infra/network-gitops/actions/workflows/validate.yml?query=branch%3Amain)
<!-- gitops-status:end -->

Reviewed desired state for RE8CH Gateway, DNS, Cilium and cross-cluster
networking. GitHub holds accepted intent and immutable artifacts; Kubernetes
holds runtime state. GitHub Actions and the bounded cloud SSA executor form the
permanently selected write path. Local Flux writers are forbidden.

## Context chain

```text
Project → parent Issue → Issue → branch/worktree → signed commits → PR
        → checks → accepted artifact → runtime evidence → Project status
```

Use [the Project context template](.github/PROJECT_CONTEXT_TEMPLATE.md). Runtime
output, recovery timelines and traffic-probe narratives belong in Issues, the
[Wiki](https://github.com/pillars-infra/network-gitops/wiki), or observability.

## Authority

- Production composition: `clusters/re8ch`
- Native contracts: `operations/releases/compile_native.py`
- Helm contracts: `operations/releases/compile_helm.py`
- Accepted replay: `.github/workflows/networking-reconcile.yml`
- New publication: `.github/workflows/static-release.yml`

The service-backend public-mesh inventory defines R640 public authority. Read its
authenticated topology contract for public IP, route, Gateway, listener, DNAT,
eBGP, overlay or dummy-interface work.

Existing resources use exact inventories, resource-version preconditions and
bounded field ownership. Images, charts and compiled artifacts remain digest
locked. Runtime acceptance combines artifact verification, server preflight,
accepted state and actual endpoint evidence.

## Working here

1. Start from current `github/main` in an Issue-specific `codex/*` worktree.
2. Keep one concern in the worktree and closing PR.
3. Build each source revision once and reuse its signed digest.
4. Record checks and sanitized runtime evidence in the Issue.
5. Update Project status after the corresponding evidence is verified.

Comments explain network invariants, ownership boundaries and external
contracts. Issues and Wiki carry examples, investigations and Kubernetes output.

References: [`docs/RE8CH-TOOLS.md`](docs/RE8CH-TOOLS.md),
[`docs/r640-cilium-gateway-recovery-2026-10-19.md`](docs/r640-cilium-gateway-recovery-2026-10-19.md).
