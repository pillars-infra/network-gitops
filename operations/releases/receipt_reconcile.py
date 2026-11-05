"""Compare a verified accepted release and replay only its drifted, owned objects."""
import json
import os
from pathlib import Path
from uuid import UUID

import yaml
from ssa_executor import Executor, Store, object_identity


def comparable(obj):
    # Ignore API bookkeeping and asynchronous status. Keep meaningful spec and metadata.
    obj.pop("status", None)
    for key in ("resourceVersion", "generation", "managedFields"):
        obj["metadata"].pop(key, None)
    return obj


def run(report):
    root = Path(os.environ["RUNNER_TEMP"])
    contract = yaml.safe_load(Path(os.environ["CONTRACT"]).read_text())
    operation = json.loads((root / "operation.json").read_text())
    rid = operation["releaseId"]
    digest = operation["bundle"]["digest"]
    report.update(release=rid, digest=digest)
    executor = Executor()
    store = Store(root / "executor-state", rid)
    _, objects, _ = executor.validate(contract, operation, root / "pulled/release.bundle", store)
    manager = contract["spec"]["authorization"]["fieldManager"]
    state_ref = json.loads((root / "state-cm.json").read_text())["metadata"]

    def require_accepted():
        result = executor.command(["kubectl", "get", "configmap", state_ref["name"], "-n", state_ref["namespace"], "-o", "json"])
        state = json.loads(json.loads(result.stdout)["data"]["accepted-state.json"])
        if state["releaseId"] != rid or state["appliedDigest"] != digest or state["healthyDigest"] != digest or state["blocked"] or state.get("suspended"):
            raise ValueError("accepted state changed")

    def project(item):
        data = json.dumps(item)
        live = json.loads(executor.command(["kubectl", "get", "-f", "-", "-o", "json"], data).stdout)
        if live.get("kind") == "List":
            live, = live["items"]
        if object_identity(live) != object_identity(item):
            raise ValueError("unexpected readback identity")
        meta = live["metadata"]
        if meta.get("annotations", {}).get("delivery.re8ch.com/release-id") != rid:
            raise ValueError("release ownership differs")
        item["metadata"]["resourceVersion"] = meta["resourceVersion"]
        annotations = item["metadata"].get("annotations", {})
        audit_key = "delivery.re8ch.com/operation-id"
        if audit_key in annotations:
            annotations.pop(audit_key)
            if audit_key in meta["annotations"]:
                annotations[audit_key] = meta["annotations"][audit_key]
        argv = ["kubectl", "apply", "--server-side", "--field-manager=" + manager, "-f", "-"]
        predicted = json.loads(executor.command(argv + ["--dry-run=server", "-o", "json"], json.dumps(item), timeout=120).stdout)
        return comparable(predicted) != comparable(live)

    require_accepted()
    prepared = executor.with_audit(objects, operation)
    changed = []
    for item in prepared:
        identity = object_identity(item)
        report["checking"] = identity
        differs = project(item)
        report["objects"].append({"id": identity, "drift": differs})
        if differs:
            changed.append(item)
    if changed:
        if rid == "agent-runtime-domain-toolhive-system":
            raise ValueError("ToolHive replay awaits dedicated runtime acceptance")
        require_accepted()
        result = executor.reconcile(contract, operation, root / "pulled/release.bundle", root / "executor-state")
        (root / "executor-result.json").write_text(json.dumps(result))
        if result["outcome"] != "healthy":
            raise ValueError("executor did not restore health")
        report["applied"] = [object_identity(item) for item in changed]
    require_accepted()
    for item in prepared:
        report["checking"] = object_identity(item)
        if project(item):
            raise ValueError("readback differs")
    healthy, _ = executor.wait_healthy(prepared, 0, contract["spec"]["lifecycle"].get("healthChecks"))
    report.pop("checking", None)
    report["outcome"] = ("recovered" if changed else "aligned") if healthy else "unhealthy"
    return healthy


if __name__ == "__main__":
    report = {"delivery": str(UUID(os.environ["DELIVERY_ID"])), "objects": [], "applied": []}
    try:
        success = run(report)
    except Exception as error:
        # API errors can contain decrypted values or command input.
        report.update(outcome="blocked", error=type(error).__name__)
        if type(error) is ValueError and str(error) in {"accepted state changed", "release ownership differs", "ToolHive replay awaits dedicated runtime acceptance", "readback differs", "executor did not restore health"}:
            report["reason"] = str(error)
        success = False
    print(json.dumps(report))
    raise SystemExit(0 if success else 1)
