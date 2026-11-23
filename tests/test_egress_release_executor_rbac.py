import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
NAME = "networking-native-egress-fabric-release-executor"


def objects():
    return [
        document
        for document in yaml.safe_load_all(
            (ROOT / "clusters/re8ch/resources.yaml").read_text()
        )
        if document
    ]


def test_egress_executor_rbac_exactly_matches_generated_contract_authority():
    source = objects()
    role = next(
        item
        for item in source
        if item["kind"] == "Role"
        and item["metadata"].get("namespace") == "egress-fabric"
        and item["metadata"]["name"] == NAME
    )
    binding = next(
        item
        for item in source
        if item["kind"] == "RoleBinding"
        and item["metadata"].get("namespace") == "egress-fabric"
        and item["metadata"]["name"] == NAME
    )
    ledger = json.loads(
        (ROOT / "operations/releases/native-authority.json").read_text()
    )
    release = next(
        item
        for item in ledger["releases"]
        if item["releaseId"] == "networking-native-egress-fabric"
    )

    assert role["rules"] == release["rules"]
    assert binding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "Role",
        "name": NAME,
    }
    assert binding["subjects"] == [
        {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Group",
            "name": ledger["executionGroup"],
        }
    ]
    assert all(subject["kind"] != "ServiceAccount" for subject in binding["subjects"])
