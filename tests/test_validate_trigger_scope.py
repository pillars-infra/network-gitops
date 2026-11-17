from fnmatch import fnmatch
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/validate.yml"


def triggers():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)["on"]


def test_pull_requests_keep_complete_validation():
    assert triggers()["pull_request"] == ""


def test_main_push_skips_only_static_context_surfaces():
    push = triggers()["push"]
    ignored = push["paths-ignore"]
    static_paths = (
        "site/index.html",
        "README.md",
        "AGENTS.md",
        "docs/CROSS-ORGANIZATION-CONTEXT.md",
        ".github/ISSUE_TEMPLATE/context.yml",
        ".github/pull_request_template.md",
        ".github/PROJECT_CONTEXT_TEMPLATE.md",
        ".github/workflows/pages.yml",
    )
    runtime_paths = (
        "contracts/networking-gateway.yaml",
        "releases/networking-gateway/kustomization.yaml",
        "operations/releases/compile_native.py",
        "policies/validate.py",
        ".github/workflows/validate.yml",
    )

    assert push["branches"] == ["main"]
    assert all(any(fnmatch(path, pattern) for pattern in ignored) for path in static_paths)
    assert all(not any(fnmatch(path, pattern) for pattern in ignored) for path in runtime_paths)
