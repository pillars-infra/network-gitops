import datetime as dt
import importlib.util
import io
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "operations/releases"))
from unified_bundle import canonical, compile_bundle, digest

SPEC = importlib.util.spec_from_file_location("ssa_executor", ROOT / "operations/releases/ssa_executor.py")
executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(executor)

MATERIALIZE_SPEC = importlib.util.spec_from_file_location(
    "operation_materialize", ROOT / "operations/releases/operation_materialize.py")
materialize = importlib.util.module_from_spec(MATERIALIZE_SPEC)
MATERIALIZE_SPEC.loader.exec_module(materialize)

NOW = dt.datetime(2026, 10, 23, tzinfo=dt.timezone.utc)


def contract(inventory=None, deletion=None):
    inventory = inventory or ["apps/Deployment/demo/demo"]
    return {
        "apiVersion": "delivery.re8ch.com/v1alpha1", "kind": "ReleaseContract",
        "metadata": {"name": "demo"},
        "spec": {
            "target": {"cluster": "re8ch", "namespace": "demo"},
            "source": {"renderer": "kustomize", "revision": "a" * 40},
            "provenance": {
                "repository": "re8ch/delivery-products-gitops", "workflow": ".github/workflows/static-release.yml",
                "ref": "refs/heads/main", "environment": "production",
                "audience": "https://kube-api.re8ch.com/release-executor",
                "signer": "https://github.com/re8ch/delivery-products-gitops/.github/workflows/static-release.yml@refs/heads/main",
                "issuer": "https://token.actions.githubusercontent.com",
            },
            "authorization": {"fieldManager": "re8ch-release/demo", "resources": ["apps/Deployment"], "objectNames": ["demo"]},
            "inventory": {"digest": digest(canonical(inventory))},
            "lifecycle": {"prune": True, "healthTimeoutSeconds": 1, "protectedKinds": [], "deletionAllowlist": deletion or []},
        },
    }


def rendered(name="demo"):
    return f"""apiVersion: apps/v1
kind: Deployment
metadata: {{name: {name}, namespace: demo}}
spec:
  replicas: 1
  template:
    spec:
      containers:
      - {{name: demo, image: 'registry.example/demo@sha256:{'a' * 64}'}}
""".encode()


def prepare(tmp_path, sequence=1, operation_id=None, previous=None):
    value = contract()
    archive, manifest = compile_bundle(value, rendered())
    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(archive)
    operation = {
        "apiVersion": "delivery.re8ch.com/release-operation/v1alpha1",
        "operationId": operation_id or str(uuid.uuid4()), "sequence": sequence,
        "action": "reconcile", "idempotencyKey": "0123456789abcdef",
        "releaseId": "demo", "target": "re8ch/demo", "contractDigest": digest(canonical(value)),
        "bundle": {"reference": "oci://registry.example/releases/demo", "digest": digest(archive),
                   "payloadDigest": digest(archive),
                   "signer": "https://github.com/re8ch/delivery-products-gitops/.github/workflows/static-release.yml@refs/heads/main",
                   "issuer": "https://token.actions.githubusercontent.com"},
        "inventoryDigest": manifest["inventoryDigest"],
        "github": {"repository": "re8ch/delivery-products-gitops", "workflow": ".github/workflows/static-release.yml",
                   "ref": "refs/heads/main", "commit": "b" * 40, "runId": "123", "environment": "production",
                   "audience": "https://kube-api.re8ch.com/release-executor"},
        "issuedAt": (NOW - dt.timedelta(minutes=1)).isoformat(),
        "expiresAt": (NOW + dt.timedelta(minutes=10)).isoformat(), "nonce": "0123456789abcdef",
    }
    if previous:
        operation["previousApprovedDigest"] = previous
    return value, operation, bundle_path


def staged_release(tmp_path, suffix, deployment_version, config_value, revision="a" * 40):
    documents = f"""apiVersion: apps/v1
kind: Deployment
metadata: {{name: demo, namespace: demo, labels: {{drill: '{deployment_version}'}}}}
spec:
  replicas: 1
  template:
    spec:
      containers:
      - {{name: demo, image: 'registry.example/demo@sha256:{'a' * 64}'}}
---
apiVersion: v1
kind: ConfigMap
metadata: {{name: demo-config, namespace: demo}}
data: {{value: '{config_value}'}}
""".encode()
    inventory = ["apps/Deployment/demo/demo", "core/ConfigMap/demo/demo-config"]
    value = contract(inventory)
    value["spec"]["source"]["revision"] = revision
    value["spec"]["authorization"]["resources"] = ["apps/Deployment", "core/ConfigMap"]
    value["spec"]["authorization"]["objectNames"] = ["demo", "demo-config"]
    value["spec"]["lifecycle"]["stages"] = [
        {"name": "runtime", "kinds": ["Deployment"]},
        {"name": "custom-resources", "kinds": ["ConfigMap"]},
    ]
    archive, manifest = compile_bundle(value, documents)
    path = tmp_path / f"{suffix}.tar.gz"
    path.write_bytes(archive)
    return value, archive, manifest, path


def operation_for(value, archive, manifest, sequence, previous=None, action="reconcile"):
    operation = {
        "apiVersion": "delivery.re8ch.com/release-operation/v1alpha1",
        "operationId": str(uuid.uuid4()), "sequence": sequence, "action": action,
        "idempotencyKey": uuid.uuid4().hex, "releaseId": "demo", "target": "re8ch/demo",
        "contractDigest": digest(canonical(value)),
        "bundle": {"reference": "oci://registry.example/releases/demo", "digest": digest(archive),
                   "payloadDigest": digest(archive),
                   "signer": "https://github.com/re8ch/delivery-products-gitops/.github/workflows/static-release.yml@refs/heads/main",
                   "issuer": "https://token.actions.githubusercontent.com"},
        "inventoryDigest": manifest["inventoryDigest"],
        "github": {"repository": "re8ch/delivery-products-gitops", "workflow": ".github/workflows/static-release.yml",
                   "ref": "refs/heads/main", "commit": "b" * 40, "runId": "123", "environment": "production",
                   "audience": "https://kube-api.re8ch.com/release-executor"},
        "issuedAt": (NOW - dt.timedelta(minutes=1)).isoformat(),
        "expiresAt": (NOW + dt.timedelta(minutes=10)).isoformat(), "nonce": uuid.uuid4().hex,
    }
    if previous:
        operation["previousApprovedDigest"] = previous
    if action == "rollback":
        operation["approvalRef"] = "change/ceph-rollback-drill"
    return operation


class Runner:
    def __init__(self, conflict=False, live=None, pulled_bundle=None):
        self.calls = []
        self.conflict = conflict
        self.live = live
        self.pulled_bundle = pulled_bundle

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs.get("input")))
        if self.conflict and "--dry-run=server" in argv and "--force-conflicts" not in argv:
            return subprocess.CompletedProcess(argv, 1, "", "field manager conflict")
        if argv[:2] == ["kubectl", "get"]:
            body = self.live or {"metadata": {"generation": 2}, "spec": {"replicas": 1},
                                 "status": {"observedGeneration": 2, "availableReplicas": 1}}
            return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")
        if argv[:3] == ["flux", "pull", "artifact"] and self.pulled_bundle:
            Path(argv[argv.index("--output") + 1], "release.bundle").write_bytes(self.pulled_bundle)
        return subprocess.CompletedProcess(argv, 0, "ok", "")


def test_reconcile_dry_runs_applies_persists_and_is_idempotent(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    runner = Runner()
    instance = executor.Executor(runner=runner, now=lambda: NOW, sleeper=lambda _: None)
    result = instance.reconcile(value, operation, bundle_path, tmp_path / "state", verify_signature=False)
    assert result["outcome"] == "healthy"
    apply_calls = [call for call in runner.calls if call[0][:2] == ["kubectl", "apply"]]
    assert len(apply_calls) == 2
    assert "--dry-run=server" in apply_calls[0][0]
    assert "--field-manager=re8ch-release/demo" in apply_calls[1][0]
    persisted = json.loads((tmp_path / "state/state/demo.json").read_text())
    assert persisted["inventory"] == ["apps/Deployment/demo/demo"]
    assert persisted["bundleReference"] == "oci://registry.example/releases/demo"
    assert persisted["payloadDigest"] == operation["bundle"]["payloadDigest"]
    count = len(runner.calls)
    assert instance.reconcile(value, operation, bundle_path, tmp_path / "state", verify_signature=False) == result
    assert len(runner.calls) == count


def test_explicit_empty_stage_selection_finalizes_without_applying_objects(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    runner = Runner()
    result = executor.Executor(runner=runner, now=lambda: NOW, sleeper=lambda _: None).reconcile(
        value, operation, bundle_path, tmp_path / "state", verify_signature=False, stages=set(), finalize=True)
    assert result["outcome"] == "healthy"
    assert not [call for call in runner.calls if call[0][:2] == ["kubectl", "apply"]]
    persisted = json.loads((tmp_path / "state/state/demo.json").read_text())
    assert persisted["inventory"] == ["apps/Deployment/demo/demo"]


def test_durable_state_is_a_server_side_apply_configmap(monkeypatch, tmp_path):
    state_dir = tmp_path / "state-root"
    (state_dir / "state").mkdir(parents=True)
    state = {"releaseId": "demo", "sequence": 1}
    result = {"releaseId": "demo", "outcome": "healthy"}
    (state_dir / "state/demo.json").write_text(json.dumps(state))
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result))
    output = tmp_path / "configmap.json"
    monkeypatch.setattr(materialize, "validate_schema", lambda *_: None)
    materialize.persist(state_dir, "demo", "toolhive-system", result_path, output)
    manifest = json.loads(output.read_text())
    assert manifest["apiVersion"] == "v1"
    assert manifest["kind"] == "ConfigMap"
    assert manifest["metadata"] == {"name": "ssa-state-demo", "namespace": "toolhive-system"}
    assert json.loads(manifest["data"]["accepted-state.json"]) == state
    assert json.loads(manifest["data"]["last-result.json"]) == result


def test_kubectl_commands_refresh_actions_oidc_token(monkeypatch):
    runner = Runner()
    instance = executor.Executor(runner=runner)
    monkeypatch.setattr(instance, "actions_kube_token", lambda: "fresh-token")
    instance.command(["kubectl", "get", "namespace", "demo"])
    assert runner.calls[0][0][:3] == ["kubectl", "--token=fresh-token", "get"]


def test_actions_oidc_refresh_is_cached_and_audience_bounded(monkeypatch):
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", "https://pipelines.actions.githubusercontent.com/token?api-version=2.0")
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "request-token")
    monkeypatch.setenv("EXECUTOR_AUDIENCE", "https://kube-api.re8ch.com/release-executor-ceph-infra")
    requests = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def open_token(request, timeout):
        requests.append(request)
        assert timeout == 30
        return Response(b'{"value":"fresh-token"}')

    monkeypatch.setattr(executor.urllib.request, "urlopen", open_token)
    instance = executor.Executor()
    assert instance.actions_kube_token() == "fresh-token"
    assert instance.actions_kube_token() == "fresh-token"
    assert len(requests) == 1
    monkeypatch.setenv("EXECUTOR_AUDIENCE", "https://attacker.example/release-executor-ceph-infra")
    rejected = executor.Executor()
    with pytest.raises(executor.Rejected, match="unexpected executor audience"):
        rejected.actions_kube_token()


def test_normal_apply_does_not_reclaim_conflicting_fields(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    runner = Runner(conflict=True)
    with pytest.raises(executor.Rejected, match="field manager conflict"):
        executor.Executor(runner=runner, now=lambda: NOW).reconcile(
            value, operation, bundle_path, tmp_path / "state", verify_signature=False)
    apply_calls = [call for call in runner.calls if call[0][:2] == ["kubectl", "apply"]]
    assert len(apply_calls) == 1
    assert "--force-conflicts" not in apply_calls[0][0]


def test_force_conflicts_requires_action_and_contract_identity(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    identity = "apps/Deployment/demo/demo"
    value["spec"]["authorization"]["forceConflictObjects"] = [identity]
    archive, manifest = compile_bundle(value, rendered())
    bundle_path.write_bytes(archive)
    operation["contractDigest"] = digest(canonical(value))
    operation["bundle"]["digest"] = digest(archive)
    operation["bundle"]["payloadDigest"] = digest(archive)
    operation["inventoryDigest"] = manifest["inventoryDigest"]
    operation["action"] = "force-reconcile"
    operation["forceConflictObjects"] = [identity]
    runner = Runner(conflict=True)
    result = executor.Executor(runner=runner, now=lambda: NOW).reconcile(value, operation, bundle_path, tmp_path / "state", False)
    assert result["outcome"] == "healthy"
    assert all("--force-conflicts" in call[0] for call in runner.calls if call[0][:2] == ["kubectl", "apply"])


def test_explicit_health_check_reads_live_json_pointer():
    item = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "demo", "namespace": "demo"}}
    check = {"apiVersion": "v1", "kind": "ConfigMap", "name": "demo", "namespace": "demo",
             "jsonPointer": "/data/authority", "equals": "executor"}
    healthy = executor.Executor(runner=Runner(live={"data": {"authority": "executor"}}))
    unhealthy = executor.Executor(runner=Runner(live={"data": {"authority": "drift"}}))
    assert healthy.healthy(item, [check]) == (True, "contract health checks satisfied")
    assert unhealthy.healthy(item, [check]) == (False, "/data/authority differs from contract")


def test_completed_job_does_not_require_observed_generation():
    item = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "migrate", "namespace": "demo"}}
    live = {"metadata": {"generation": 1}, "spec": {"completions": 1}, "status": {"succeeded": 1}}
    assert executor.Executor(runner=Runner(live=live)).healthy(item) == (True, "job incomplete")


def test_rollback_pull_keeps_oci_scheme(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    archive = bundle_path.read_bytes()
    manifest, objects = executor.load_archive(bundle_path)
    previous = {
        "appliedDigest": operation["bundle"]["digest"],
        "bundleReference": operation["bundle"]["reference"],
        "payloadDigest": digest(archive),
        "inventory": manifest["inventory"],
        "objectRefs": [executor.object_ref(item) for item in objects],
    }
    runner = Runner(pulled_bundle=archive)
    instance = executor.Executor(runner=runner, now=lambda: NOW, sleeper=lambda _: None)
    observed, _ = instance.rollback(previous, manifest, objects, value, operation, "re8ch-release/demo",
                                    executor.Store(tmp_path / "state", "demo"), "drill")
    pull = next(call[0] for call in runner.calls if call[0][:3] == ["flux", "pull", "artifact"])
    assert pull[3].startswith("oci://registry.example/releases/demo@sha256:")
    assert observed == operation["bundle"]["digest"]
    applied = [json.loads(call[1]) for call in runner.calls if call[0][:2] == ["kubectl", "apply"]]
    assert all(item["metadata"]["annotations"]["delivery.re8ch.com/operation-id"] == operation["operationId"]
               for item in applied)


def test_explicit_rollback_restores_only_runtime_stage_and_records_history(tmp_path):
    value, old_archive, old_manifest, old_path = staged_release(tmp_path, "old", "old", "stable")
    new_value, new_archive, new_manifest, new_path = staged_release(
        tmp_path, "new", "new", "stable", revision="c" * 40)
    state_root = tmp_path / "state"
    instance = executor.Executor(runner=Runner(), now=lambda: NOW, sleeper=lambda _: None)
    old_operation = operation_for(value, old_archive, old_manifest, 1)
    instance.reconcile(value, old_operation, old_path, state_root, verify_signature=False)
    new_operation = operation_for(new_value, new_archive, new_manifest, 2, old_operation["bundle"]["digest"])
    instance.reconcile(new_value, new_operation, new_path, state_root, verify_signature=False)

    rollback = operation_for(new_value, old_archive, old_manifest, 3, new_operation["bundle"]["digest"], "rollback")
    result = instance.reconcile(
        new_value, rollback, old_path, state_root, verify_signature=False, stages={"runtime"},
        current_bundle_path=new_path, rollback_stages={"runtime"})
    assert result["outcome"] == "rolled-back"
    assert result["rollbackDigest"] == old_operation["bundle"]["digest"]
    state = json.loads((state_root / "state/demo.json").read_text())
    assert state["appliedDigest"] == old_operation["bundle"]["digest"]
    assert [item["appliedDigest"] for item in state["history"]] == [new_operation["bundle"]["digest"]]


def test_explicit_rollback_rejects_changes_outside_runtime_stage(tmp_path):
    value, old_archive, old_manifest, old_path = staged_release(tmp_path, "old", "old", "old-config")
    new_value, new_archive, new_manifest, new_path = staged_release(
        tmp_path, "new", "new", "new-config", revision="c" * 40)
    state_root = tmp_path / "state"
    instance = executor.Executor(runner=Runner(), now=lambda: NOW, sleeper=lambda _: None)
    old_operation = operation_for(value, old_archive, old_manifest, 1)
    instance.reconcile(value, old_operation, old_path, state_root, verify_signature=False)
    new_operation = operation_for(new_value, new_archive, new_manifest, 2, old_operation["bundle"]["digest"])
    instance.reconcile(new_value, new_operation, new_path, state_root, verify_signature=False)
    rollback = operation_for(new_value, old_archive, old_manifest, 3, new_operation["bundle"]["digest"], "rollback")
    with pytest.raises(executor.Rejected, match="outside approved stages"):
        instance.reconcile(
            new_value, rollback, old_path, state_root, verify_signature=False, stages={"runtime"},
            current_bundle_path=new_path, rollback_stages={"runtime"})


def test_expired_out_of_order_and_reused_operation_are_rejected(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    operation["expiresAt"] = (NOW - dt.timedelta(seconds=1)).isoformat()
    with pytest.raises(executor.Rejected, match="stale"):
        executor.Executor(now=lambda: NOW).reconcile(value, operation, bundle_path, tmp_path / "state", False)
    value, operation, bundle_path = prepare(tmp_path, sequence=2)
    with pytest.raises(executor.Rejected, match="expected sequence 1"):
        executor.Executor(now=lambda: NOW).reconcile(value, operation, bundle_path, tmp_path / "state2", False)


@pytest.mark.parametrize("field", ["repository", "workflow", "ref", "environment", "audience"])
def test_operation_cannot_self_authorize_github_provenance(tmp_path, field):
    value, operation, bundle_path = prepare(tmp_path)
    operation["github"][field] = "attacker/value"
    if field == "workflow":
        operation["github"][field] = ".github/workflows/attacker.yml"
    elif field == "ref":
        operation["github"][field] = "refs/heads/attacker"
    elif field == "audience":
        operation["github"][field] = "https://attacker.example"
    with pytest.raises(executor.Rejected, match=f"GitHub {field}"):
        executor.Executor(now=lambda: NOW).reconcile(value, operation, bundle_path, tmp_path / "state", False)


def test_operation_cannot_self_authorize_signer(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    operation["bundle"]["signer"] = "https://github.com/attacker/workflow@refs/heads/main"
    with pytest.raises(executor.Rejected, match="bundle signer"):
        executor.Executor(now=lambda: NOW).reconcile(value, operation, bundle_path, tmp_path / "state", False)


def test_archive_path_or_extra_member_is_rejected(tmp_path):
    import gzip
    import io
    import tarfile
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        info = tarfile.TarInfo("../objects.json")
        info.size = 2
        archive.addfile(info, io.BytesIO(b"[]"))
    path = tmp_path / "bad.tar.gz"
    path.write_bytes(gzip.compress(raw.getvalue()))
    with pytest.raises(executor.Rejected, match="unexpected archive members"):
        executor.load_archive(path)


@pytest.mark.parametrize("fault", [None, "blocked", "suspended", "healthyDigest", "releaseId", "bundleReference", "inventoryDigest", "namespace"])
def test_replay_resolves_only_target_bound_healthy_acceptance(tmp_path, fault):
    import yaml
    value, operation, bundle_path = prepare(tmp_path)
    instance = executor.Executor(runner=Runner(), now=lambda: NOW, sleeper=lambda _: None)
    instance.reconcile(value, operation, bundle_path, tmp_path / "state", verify_signature=False)
    state = executor.Store(tmp_path / "state", "demo").state()
    state["bundleReference"] = "oci://ghcr.io/pillars-infra/network-gitops-release/demo"
    if fault in {"blocked", "suspended"}:
        state[fault] = True
    elif fault in {"healthyDigest", "inventoryDigest"}:
        state[fault] = "sha256:" + "f" * 64
    elif fault == "releaseId":
        state[fault] = "another-release"
    elif fault == "bundleReference":
        state[fault] = "oci://untrusted.example/demo"
    cm = {"metadata": {"name": "ssa-state-demo", "namespace": "other" if fault == "namespace" else "demo"},
          "data": {"accepted-state.json": json.dumps(state)}}
    cm_path = tmp_path / "cm.json"
    cm_path.write_text(json.dumps(cm))
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.safe_dump(value))
    if fault:
        with pytest.raises(ValueError):
            materialize.accepted_bundle(cm_path, contract_path)
    else:
        assert materialize.accepted_bundle(cm_path, contract_path) == {
            "reference": state["bundleReference"], "digest": state["appliedDigest"]}


def test_state_patch_does_not_write_unchanged_state_after_rejection(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    root = tmp_path / "state"
    result = executor.Executor(runner=Runner(), now=lambda: NOW).reconcile(
        value, operation, bundle_path, root, verify_signature=False)
    state = executor.Store(root, "demo").state()
    cm_path = tmp_path / "cm.json"
    cm_path.write_text(json.dumps({"metadata": {"name": "ssa-state-demo", "resourceVersion": "72"},
                                  "data": {"accepted-state.json": json.dumps(state), "last-result.json": json.dumps(result)}}))
    result_path = tmp_path / "result.json"
    result_path.write_text("")
    patch_path = tmp_path / "patch.json"
    patch_path.write_text("stale patch from earlier attempt")
    materialize.state_patch(cm_path, root, "demo", result_path, patch_path)
    assert not patch_path.exists()


def test_state_patch_persists_new_result_with_original_version(tmp_path):
    value, operation, bundle_path = prepare(tmp_path)
    root = tmp_path / "state"
    instance = executor.Executor(runner=Runner(), now=lambda: NOW)
    first = instance.reconcile(value, operation, bundle_path, root, verify_signature=False)
    previous = executor.Store(root, "demo").state()
    cm_path = tmp_path / "cm.json"
    cm_path.write_text(json.dumps({"metadata": {"name": "ssa-state-demo", "resourceVersion": "73"},
                                  "data": {"accepted-state.json": json.dumps(previous), "last-result.json": json.dumps(first)}}))
    _, replay, _ = prepare(tmp_path, sequence=2, previous=previous["appliedDigest"])
    result = instance.reconcile(value, replay, bundle_path, root, verify_signature=False)
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result))
    patch_path = tmp_path / "patch.json"
    materialize.state_patch(cm_path, root, "demo", result_path, patch_path)
    patch = json.loads(patch_path.read_text())
    assert patch["metadata"]["resourceVersion"] == "73"
    assert json.loads(patch["data"]["accepted-state.json"])["sequence"] == 2
    assert json.loads(patch["data"]["last-result.json"]) == result


def test_failed_rollback_remains_blocked_on_next_cloud_worker(tmp_path, monkeypatch):
    value, operation, bundle_path = prepare(tmp_path)
    state_root = tmp_path / "state"
    instance = executor.Executor(runner=Runner(), now=lambda: NOW, sleeper=lambda _: None)
    instance.reconcile(value, operation, bundle_path, state_root, verify_signature=False)
    previous = executor.Store(state_root, "demo").state()
    cm = {"metadata": {"name": "ssa-state-demo", "namespace": "demo", "resourceVersion": "71"},
          "data": {"accepted-state.json": json.dumps(previous)}}
    cm_path = tmp_path / "original-cm.json"
    cm_path.write_text(json.dumps(cm))
    _, replay, _ = prepare(tmp_path, sequence=2, previous=previous["appliedDigest"])
    monkeypatch.setattr(instance, "wait_healthy", lambda *args: (False, "not ready"))
    def failed_rollback(*args):
        raise executor.Rejected("previous artifact could not recover health")
    monkeypatch.setattr(instance, "rollback", failed_rollback)
    with pytest.raises(executor.Rejected, match="rollback failed"):
        instance.reconcile(value, replay, bundle_path, state_root, verify_signature=False)
    result_path = tmp_path / "result.json"
    result_path.write_text("")  # CLI failed before producing a successful result.
    patch_path = tmp_path / "patch.json"
    materialize.state_patch(cm_path, state_root, "demo", result_path, patch_path)
    patch = json.loads(patch_path.read_text())
    assert patch["metadata"] == {"resourceVersion": "71"}
    assert set(patch["data"]) == {"accepted-state.json"}
    assert json.loads(patch["data"]["accepted-state.json"])["blocked"] is True
    cm["data"].update(patch["data"])
    cm_path.write_text(json.dumps(cm))
    next_root = tmp_path / "fresh-cloud-worker"
    materialize.hydrate(cm_path, next_root, "demo")
    runner = Runner()
    with pytest.raises(executor.Rejected, match="release is blocked"):
        executor.Executor(runner=runner, now=lambda: NOW).reconcile(value, replay, bundle_path, next_root)
    assert runner.calls == []
