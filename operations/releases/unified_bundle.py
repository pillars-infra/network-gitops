#!/usr/bin/env python3
"""Compile renderer output into the single immutable Wave 5 bundle format.

Rendering remains a GitHub compiler responsibility.  This module deliberately
accepts the rendered YAML boundary used by both Helm and Kustomize, so the
runtime executor never needs either renderer or source credentials.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
CLUSTER_SCOPED = {
    "APIService", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition",
    "Namespace", "Node", "PersistentVolume", "StorageClass", "ValidatingWebhookConfiguration",
    "MutatingWebhookConfiguration", "CSIDriver", "PriorityClass", "RuntimeClass",
    "VolumeSnapshotClass", "ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding",
}
MAX_RENDERED_BYTES = 10 * 1024 * 1024
MAX_OBJECTS = 500


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def validate_schema(value: object, name: str) -> None:
    import jsonschema
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(value)


def api_group(api_version: str) -> str:
    return api_version.split("/", 1)[0] if "/" in api_version else "core"


def object_identity(document: dict) -> str:
    metadata = document.get("metadata") or {}
    namespace = metadata.get("namespace", "_")
    return f"{api_group(document['apiVersion'])}/{document['kind']}/{namespace}/{metadata['name']}"


def assert_pinned_images(value: object, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key == "image" and isinstance(child, str) and "@sha256:" not in child:
                raise ValueError(f"mutable image at {child_path}: {child}")
            assert_pinned_images(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_pinned_images(child, f"{path}[{index}]")


def normalize_documents(rendered: bytes, contract: dict) -> tuple[list[dict], list[str]]:
    if len(rendered) > MAX_RENDERED_BYTES:
        raise ValueError(f"rendered input exceeds {MAX_RENDERED_BYTES} bytes")
    spec = contract["spec"]
    namespace = spec["target"]["namespace"]
    authorization = spec["authorization"]
    allowed_resources = set(authorization["resources"])
    allowed_names = set(authorization["objectNames"])
    allow_cluster = authorization.get("allowClusterScoped", False)
    documents: list[dict] = []
    identities: set[str] = set()
    for position, raw in enumerate(yaml.safe_load_all(rendered), start=1):
        if raw is None:
            continue
        if not isinstance(raw, dict) or not all(key in raw for key in ("apiVersion", "kind", "metadata")):
            raise ValueError(f"document {position} is not a Kubernetes object")
        metadata = raw.get("metadata") or {}
        name = metadata.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"document {position} has no metadata.name")
        resource = f"{api_group(raw['apiVersion'])}/{raw['kind']}"
        if resource not in allowed_resources or name not in allowed_names:
            raise ValueError(f"undeclared object: {resource}/{name}")
        if raw["kind"] in CLUSTER_SCOPED:
            if not allow_cluster:
                raise ValueError(f"cluster-scoped object is forbidden: {resource}/{name}")
            if metadata.get("namespace"):
                raise ValueError(f"cluster-scoped object declares namespace: {resource}/{name}")
        elif metadata.get("namespace") != namespace:
            raise ValueError(f"object must declare exact namespace {namespace}: {resource}/{name}")
        if raw["kind"] == "Secret":
            raise ValueError(f"Secret payloads are forbidden in release bundles: {name}")
        assert_pinned_images(raw)
        identity = object_identity(raw)
        if identity in identities:
            raise ValueError(f"duplicate object identity: {identity}")
        identities.add(identity)
        documents.append(raw)
        if len(documents) > MAX_OBJECTS:
            raise ValueError(f"bundle exceeds {MAX_OBJECTS} objects")
    if not documents:
        raise ValueError("bundle contains no Kubernetes objects")
    documents.sort(key=object_identity)
    return documents, sorted(identities)


def deterministic_archive(files: dict[str, bytes]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size = len(files[name])
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(files[name]))
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        compressed.write(raw.getvalue())
    return output.getvalue()


def compile_bundle(contract: dict, rendered: bytes) -> tuple[bytes, dict]:
    validate_schema(contract, "release-contract.schema.json")
    documents, inventory = normalize_documents(rendered, contract)
    objects = canonical(documents)
    inventory_bytes = canonical(inventory)
    configured_stages = contract["spec"]["lifecycle"].get("stages") or [
        {"name": "runtime", "kinds": sorted({item["kind"] for item in documents})}
    ]
    assigned: set[str] = set()
    stages = []
    for stage in configured_stages:
        identities = sorted(object_identity(item) for item in documents if item["kind"] in set(stage["kinds"]))
        duplicate = assigned.intersection(identities)
        if duplicate:
            raise ValueError(f"objects assigned to multiple stages: {sorted(duplicate)}")
        assigned.update(identities)
        stages.append({"name": stage["name"], "inventory": identities})
    missing = set(inventory) - assigned
    if missing:
        raise ValueError(f"objects are not assigned to a stage: {sorted(missing)}")
    manifest = {
        "schemaVersion": "delivery.re8ch.com/release-bundle/v1alpha1",
        "releaseId": contract["metadata"]["name"],
        "renderer": contract["spec"]["source"]["renderer"],
        "revision": contract["spec"]["source"]["revision"],
        "contractDigest": digest(canonical(contract)),
        "renderedDigest": digest(objects),
        "inventoryDigest": digest(inventory_bytes),
        "inventory": inventory,
        "stages": stages,
        "objectsFile": "objects.json",
    }
    validate_schema(manifest, "release-bundle-manifest.schema.json")
    expected = contract["spec"]["inventory"]["digest"]
    if expected != manifest["inventoryDigest"]:
        raise ValueError(f"inventory digest mismatch: contract={expected}, rendered={manifest['inventoryDigest']}")
    files = {"manifest.json": canonical(manifest), "objects.json": objects}
    return deterministic_archive(files), manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--rendered", type=Path, required=True, help="Helm or Kustomize rendered multi-document YAML")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    archive, manifest = compile_bundle(contract, args.rendered.read_bytes())
    args.output.write_bytes(archive)
    print(json.dumps({**manifest, "payloadDigest": digest(archive)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
