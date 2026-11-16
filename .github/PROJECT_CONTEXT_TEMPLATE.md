# Project context template

Use one Project for a product, service or governance domain.

## Hierarchy

```text
Project
├── parent Feature: durable outcome or historical phase
│   ├── Feature/Bug/Task: one reviewable concern
│   └── Feature/Bug/Task: one reviewable concern
└── parent Feature: next outcome or phase
```

Historical reconstruction groups pull requests by capability and phase. Use an
`Others` Project only while ownership remains unresolved.

## Fields

| Field | Purpose |
| --- | --- |
| Status | Todo, In Progress, Done |
| Type | Feature, Bug, Task |
| Lifecycle | Backlog, Ready, In Progress, Blocked, Done, Cancelled, Historical |
| Work Type | Feature, Bug, Task, Governance, Dependency, Documentation, Migration, Historical |
| Context Status | Draft, Ready, Complete, Historical |
| Priority / Risk | Local priority and operational exposure |
| Start Date | First meaningful work or historical PR date |
| Target Date | Planned completion |
| Completed Date | Verified completion or final historical date |

## Views

1. `List`: table with Title, Status, Repository, Type, Parent issue,
   Sub-issues progress, lifecycle, work type, context and dates.
2. `Status`: board grouped by Status with context fields visible.
3. `Timeline`: roadmap using Start Date and Completed Date; unfinished work
   uses Target Date.

## Issue context

```markdown
## Outcome
<Observable result>

## Context
- Parent Issue: #
- Project: <link>
- Milestone: <name>
- Branch/worktree: <name>

## Acceptance
- [ ] Static contract or code verification
- [ ] Runtime verification where applicable
- [ ] Evidence linked below

## Evidence
<Checks, deployment status, sanitized runtime output, observability or Wiki>
```

## Delivery

- One Issue, concern, branch and worktree form one review unit.
- Signed commits describe coherent state transitions.
- The pull request closes its Issue and links immutable build and runtime evidence.
- Each CI class runs once for an unchanged revision.
- Source comments explain invariants; Issues and Wiki carry narratives and output.
- Project status follows verified evidence.

