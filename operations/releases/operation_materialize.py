#!/usr/bin/env python3
"""Materialize typed release requests and durable ConfigMap state envelopes."""
from __future__ import annotations

from profile import replay_provenance
import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import uuid
from pathlib import Path

import yaml

from unified_bundle import canonical, digest, validate_schema


def state_configmap_name(release_id: str) -> str:
    """Return a stable DNS label for a release's durable executor state."""
    prefix = "ssa-state-"
    candidate = prefix + release_id
    if len(candidate) <= 63:
        return candidate
    suffix = hashlib.sha256(release_id.encode()).hexdigest()[:10]
    head = release_id[: 63 - len(prefix) - len(suffix) - 1].rstrip("-")
    return f"{prefix}{head}-{suffix}"


def compact(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def accepted_bundle(configmap: Path, contract_path: Path) -> dict[str, str]:
    """Resolve a replay from durable acceptance, never from an arbitrary caller URL."""
    contract = yaml.safe_load(contract_path.read_text())
    validate_schema(contract, "release-contract.schema.json")
    release_id = contract["metadata"]["name"]
    cm = json.loads(configmap.read_text())
    if (cm.get("metadata", {}).get("name") != state_configmap_name(release_id)
            or cm.get("metadata", {}).get("namespace") != contract["spec"]["target"]["namespace"]):
        raise ValueError("accepted state ConfigMap does not match the release target")
    state = json.loads(cm.get("data", {}).get("accepted-state.json", "{}"))
    validate_schema(state, "release-accepted-state.schema.json")
    if state["releaseId"] != release_id:
        raise ValueError("accepted state belongs to another release")
    if state["blocked"] or state.get("suspended"):
        raise ValueError("release is blocked or suspended")
    if state.get("healthyDigest") != state["appliedDigest"]:
        raise ValueError("replay requires a previously healthy accepted digest")
    expected = f"oci://ghcr.io/pillars-infra/network-gitops-release/{release_id}"
    if state["bundleReference"] != expected:
        raise ValueError("accepted bundle is outside the release repository")
    if state["inventoryDigest"] != contract["spec"]["inventory"]["digest"]:
        raise ValueError("contract inventory changed; publish a reviewed release instead")
    return {"reference": expected, "digest": state["appliedDigest"]}


def hydrate(configmap: Path, state_dir: Path, release_id: str) -> None:
    data = json.loads(configmap.read_text()).get("data", {})
    (state_dir / "state").mkdir(parents=True, exist_ok=True)
    (state_dir / "results" / release_id).mkdir(parents=True, exist_ok=True)
    if "accepted-state.json" in data:
        state = json.loads(data["accepted-state.json"])
        validate_schema(state, "release-accepted-state.schema.json")
        (state_dir / "state" / f"{release_id}.json").write_text(compact(state))
    if "last-result.json" in data:
        result = json.loads(data["last-result.json"])
        validate_schema(result, "release-operation-result.schema.json")
        (state_dir / "results" / release_id / f'{result["operationId"]}.json').write_text(compact(result))


def request(contract_path: Path, metadata_path: Path, state_dir: Path, reference: str,
            oci_digest: str, output: Path, action: str = "reconcile", force_objects: list[str] | None = None, replay_only: bool = False) -> None:
    contract = yaml.safe_load(contract_path.read_text())
    validate_schema(contract, "release-contract.schema.json")
    metadata = json.loads(metadata_path.read_text())
    release_id = contract["metadata"]["name"]
    state_path = state_dir / "state" / f"{release_id}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    now = dt.datetime.now(dt.timezone.utc)
    provenance = contract["spec"]["provenance"]
    operation = {
        "apiVersion": "delivery.re8ch.com/release-operation/v1alpha1",
        "operationId": str(uuid.uuid4()), "sequence": 1 if state is None else state["sequence"] + 1,
        "action": action,
        "releaseId": release_id,
        "target": f'{contract["spec"]["target"]["cluster"]}/{contract["spec"]["target"]["namespace"]}',
        "contractDigest": digest(canonical(contract)),
        "bundle": {"reference": reference, "digest": oci_digest, "payloadDigest": metadata["payloadDigest"],
                   "signer": provenance["signer"], "issuer": provenance["issuer"]},
        "inventoryDigest": metadata["inventoryDigest"],
        "github": {"repository": os.environ["GITHUB_REPOSITORY"], "workflow": provenance["workflow"],
                   "ref": os.environ["GITHUB_REF"], "commit": os.environ["GITHUB_SHA"], "runId": os.environ["GITHUB_RUN_ID"],
                   "environment": provenance["environment"], "audience": provenance["audience"]},
        "issuedAt": now.isoformat(), "expiresAt": (now + dt.timedelta(minutes=10)).isoformat(),
        "nonce": secrets.token_hex(16),
        "idempotencyKey": secrets.token_hex(16),
    }
    if replay_only:
        replay = replay_provenance(contract)
        if replay is None or action != "reconcile" or force_objects:
            raise ValueError("only accepted reconcile is authorized for the replay identity")
        operation["github"].update({key: replay[key] for key in ("workflow", "environment", "audience")})
    if state:
        operation["previousApprovedDigest"] = state["appliedDigest"]
    if force_objects:
        operation["forceConflictObjects"] = sorted(force_objects)
    validate_schema(operation, "release-operation.schema.json")
    output.write_text(compact(operation))


def persist(state_dir: Path, release_id: str, namespace: str, result_path: Path, output: Path) -> None:
    state = json.loads((state_dir / "state" / f"{release_id}.json").read_text())
    result = json.loads(result_path.read_text())
    validate_schema(state, "release-accepted-state.schema.json")
    validate_schema(result, "release-operation-result.schema.json")
    output.write_text(compact({
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": state_configmap_name(release_id), "namespace": namespace},
        "data": {"accepted-state.json": compact(state), "last-result.json": compact(result)},
    }))


def state_patch(configmap: Path, state_dir: Path, release_id: str, result_path: Path, output: Path) -> None:
    """Persist changed state even after failure, without overwriting concurrent edits."""
    cm = json.loads(configmap.read_text())
    metadata = cm.get("metadata", {})
    if metadata.get("name") != state_configmap_name(release_id) or not metadata.get("resourceVersion"):
        raise ValueError("state patch requires the original release ConfigMap and resourceVersion")
    state_path = state_dir / "state" / f"{release_id}.json"
    original = cm.get("data", {})
    changed = {}
    if state_path.exists():
        state = json.loads(state_path.read_text())
        validate_schema(state, "release-accepted-state.schema.json")
        if state["releaseId"] != release_id:
            raise ValueError("state patch belongs to another release")
        if state != json.loads(original.get("accepted-state.json", "{}")):
            changed["accepted-state.json"] = compact(state)
    if result_path.exists() and result_path.stat().st_size:
        result = json.loads(result_path.read_text())
        validate_schema(result, "release-operation-result.schema.json")
        if result["releaseId"] != release_id:
            raise ValueError("result belongs to another release")
        if result != json.loads(original.get("last-result.json", "{}")):
            changed["last-result.json"] = compact(result)
    if changed:
        output.write_text(compact({"metadata": {"resourceVersion": metadata["resourceVersion"]}, "data": changed}))
    else:
        output.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("hydrate")
    load.add_argument("--configmap", type=Path, required=True); load.add_argument("--state-dir", type=Path, required=True)
    load.add_argument("--release-id", required=True)
    make = sub.add_parser("request")
    make.add_argument("--contract", type=Path, required=True); make.add_argument("--metadata", type=Path, required=True)
    make.add_argument("--state-dir", type=Path, required=True); make.add_argument("--reference", required=True)
    make.add_argument("--digest", required=True); make.add_argument("--output", type=Path, required=True)
    make.add_argument("--action", choices=["reconcile", "force-reconcile", "reset", "suspend", "resume", "rollback"], default="reconcile")
    make.add_argument("--replay-only", action="store_true")
    make.add_argument("--force-object", action="append", default=[])
    save = sub.add_parser("persist")
    save.add_argument("--state-dir", type=Path, required=True); save.add_argument("--release-id", required=True)
    save.add_argument("--namespace", required=True)
    save.add_argument("--result", type=Path, required=True); save.add_argument("--output", type=Path, required=True)
    state_name = sub.add_parser("state-name")
    state_name.add_argument("--release-id", required=True)
    accepted = sub.add_parser("accepted-bundle")
    accepted.add_argument("--configmap", type=Path, required=True)
    accepted.add_argument("--contract", type=Path, required=True)
    patch = sub.add_parser("state-patch")
    patch.add_argument("--configmap", type=Path, required=True)
    patch.add_argument("--state-dir", type=Path, required=True)
    patch.add_argument("--release-id", required=True)
    patch.add_argument("--result", type=Path, required=True)
    patch.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "hydrate": hydrate(args.configmap, args.state_dir, args.release_id)
    elif args.command == "request": request(args.contract, args.metadata, args.state_dir, args.reference, args.digest, args.output, args.action, args.force_object, args.replay_only)
    elif args.command == "persist": persist(args.state_dir, args.release_id, args.namespace, args.result, args.output)
    elif args.command == "accepted-bundle": print(compact(accepted_bundle(args.configmap, args.contract)))
    elif args.command == "state-patch": state_patch(args.configmap, args.state_dir, args.release_id, args.result, args.output)
    else: print(state_configmap_name(args.release_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
