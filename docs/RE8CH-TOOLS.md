# RE8CH dynamic tools for GitOps agents

This page is the repository entry point for the authenticated RE8CH self-service tool catalog. It describes **how to discover and invoke** tools; it is not a snapshot of available tools or a grant of access. Tool names, schemas, backend health, and authorization can change between sessions and organizations.

## Before a platform operation

1. Read this repository's `AGENTS.md` and follow its GitOps ownership and PR rules. Identify the authenticated organization. Re8ch Admin is the infrastructure organization; Re8ch is the application tenant. Membership in one does not imply membership in the other.
2. Use the `re8ch-tenant` MCP server's `tenant_self_service_capabilities` for ordinary tenant resources and Ready namespaces. For reviewed procedures outside those resource tools, search `dynamic_skill_search` and load the relevant result.
3. If the session exposes administrator tools, call `platform_tool_catalog` **in the current session**. Inspect `unavailableBackends` and find the exact tool. Do not infer platform access from the static connector tool count or from a previous catalog response.
4. Call `platform_tool_call` with the selected entry's `backend`, tool `name` as `toolName`, and `arguments` matching that entry's current `inputSchema`. Read the complete result and audit reference. A successful transport response alone does not prove the operation succeeded.
5. If a tool is absent, its backend is unavailable, or authorization fails, report that exact condition. Do not substitute local kubeconfig, SSH credentials, another organization identity, or an unlisted backend tool.

For example, an authorized administrator may find `native/kubectl.exec` in the live catalog. Its input schema currently uses `argv` (such as `["get", "deployments", "-n", "NAMESPACE"]`), with optional `stdin` and `timeout`; copy the **live** schema before invoking it through `platform_tool_call`. Use bounded, named reads for inspection. A returned tool does not authorize a particular cluster write: apply this repository's ownership, review, and rollout rules to every mutation. For creates and material changes, use the platform plan-before-write workflow where published.

## Keeping this guidance current

The live `platform_tool_catalog` is the update mechanism for tool inventory and schemas. Query it for every new task and again if a selected tool changes or fails; do not pin a generated catalog, counts, or input schemas in Git. When the discovery/call protocol or GitOps ownership rules change, update this page and `AGENTS.md` through a signed pull request. Platform tool registration and authorization remain server-side; editing this file cannot enable a tool.
