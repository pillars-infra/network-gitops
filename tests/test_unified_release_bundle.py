import copy
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("unified_bundle", ROOT / "operations/releases/unified_bundle.py")
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


def contract(renderer="kustomize"):
    inventory = ["apps/Deployment/demo/demo"]
    return {
        "apiVersion": "delivery.re8ch.com/v1alpha1",
        "kind": "ReleaseContract",
        "metadata": {"name": "demo"},
        "spec": {
            "target": {"cluster": "re8ch", "namespace": "demo"},
            "source": {"renderer": renderer, "revision": "0123456789abcdef"},
            "provenance": {
                "repository": "re8ch/delivery-products-gitops", "workflow": ".github/workflows/static-release.yml",
                "ref": "refs/heads/main", "environment": "production",
                "audience": "https://kube-api.re8ch.com/release-executor",
                "signer": "https://github.com/re8ch/delivery-products-gitops/.github/workflows/static-release.yml@refs/heads/main",
                "issuer": "https://token.actions.githubusercontent.com",
            },
            "authorization": {
                "fieldManager": "re8ch-release/demo",
                "resources": ["apps/Deployment"],
                "objectNames": ["demo"],
            },
            "inventory": {"digest": bundle.digest(bundle.canonical(inventory))},
            "lifecycle": {"prune": True, "healthTimeoutSeconds": 300, "protectedKinds": ["PersistentVolumeClaim"]},
        },
    }


def rendered(image="registry.example/demo@sha256:" + "a" * 64):
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo
  namespace: demo
spec:
  template:
    spec:
      containers:
      - name: demo
        image: {image}
""".encode()


@pytest.mark.parametrize("renderer", ["helm", "kustomize"])
def test_both_renderers_produce_the_same_envelope_shape(renderer):
    archive, manifest = bundle.compile_bundle(contract(renderer), rendered())
    assert manifest["renderer"] == renderer
    assert manifest["inventory"] == ["apps/Deployment/demo/demo"]
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        assert source.getnames() == ["manifest.json", "objects.json"]
        assert json.load(source.extractfile("manifest.json")) == manifest


def test_archive_is_deterministic():
    first = bundle.compile_bundle(contract(), rendered())[0]
    second = bundle.compile_bundle(contract(), rendered())[0]
    assert first == second


@pytest.mark.parametrize("mutation, message", [
    (lambda value: value["metadata"].update(namespace="other"), "exact namespace"),
    (lambda value: value["metadata"].update(name="undeclared"), "undeclared object"),
    (lambda value: value.update(kind="ClusterRole", apiVersion="rbac.authorization.k8s.io/v1"), "undeclared object"),
])
def test_scope_escape_is_rejected(mutation, message):
    import yaml
    value = yaml.safe_load(rendered())
    mutation(value)
    with pytest.raises(ValueError, match=message):
        bundle.compile_bundle(contract(), yaml.safe_dump(value).encode())


def test_mutable_image_is_rejected():
    with pytest.raises(ValueError, match="mutable image"):
        bundle.compile_bundle(contract(), rendered("registry.example/demo:latest"))


def test_inventory_mismatch_and_duplicate_identity_are_rejected():
    bad = copy.deepcopy(contract())
    bad["spec"]["inventory"]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="inventory digest mismatch"):
        bundle.compile_bundle(bad, rendered())
    with pytest.raises(ValueError, match="duplicate object identity"):
        bundle.compile_bundle(contract(), rendered() + b"---\n" + rendered())


def test_oversized_input_is_rejected_before_yaml_parse(monkeypatch):
    monkeypatch.setattr(bundle, "MAX_RENDERED_BYTES", 8)
    with pytest.raises(ValueError, match="exceeds 8 bytes"):
        bundle.compile_bundle(contract(), rendered())


def test_wave5_schemas_are_valid_draft_2020_12():
    for name in (
        "release-contract.schema.json",
        "release-bundle-manifest.schema.json",
        "release-operation.schema.json",
        "release-operation-result.schema.json",
        "release-accepted-state.schema.json",
    ):
        Draft202012Validator.check_schema(json.loads((ROOT / "schemas" / name).read_text()))
