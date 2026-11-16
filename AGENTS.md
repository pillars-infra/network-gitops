# Network GitOps agent instructions

## Start work

1. Read the repository Issue and its parent outcome.
2. Start from current `github/main` in one task-specific `codex/*` worktree.
3. Read the service-backend public network authority before R640 work.
4. Discover current RE8CH tools through `docs/RE8CH-TOOLS.md`.

## Delivery context

```text
Project → parent Issue → Issue → branch/worktree → signed commits → PR
        → checks → accepted artifact → runtime evidence → Project status
```

- Give each Project item type, lifecycle, status and dates.
- Keep one concern per branch and closing PR.
- Build once per revision and reuse the immutable signed digest.
- Keep comments for network invariants, safety boundaries and external contracts.
- Put Kubernetes output, probe stories and recovery timelines in Issues, Wiki or
  observability.

## Authority

The production root is `clusters/re8ch`. Images and OCI/Helm artifacts remain
digest pinned. GitHub Actions and the bounded cloud SSA executor are the
permanently selected delivery path; local Flux writers are forbidden. Runtime
read-back completes delivery evidence.

The authenticated service-backend inventory defines R640 public authority and
fallback topology. Reviewed desired state carries lasting network changes.
Credentials and decrypted SOPS material remain in approved secret systems.
