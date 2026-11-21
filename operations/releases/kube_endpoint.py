#!/usr/bin/env python3
"""Build an executor kubeconfig and select an independent API transport."""
import base64
import os
from pathlib import Path
import subprocess
import tempfile

import yaml

from ssa_executor import Rejected


ENDPOINTS = {
    "re8ch": [
        "https://179.255.126.104:443",
        "https://179.253.231.159:443",
        "https://223.159.210.222:6443",
    ],
    "re8ch-main": [
        "https://179.255.126.104:443",
        "https://179.253.231.159:443",
        "https://223.159.210.222:6443",
    ],
    "re8ch-atlantic": ["https://2.29.219.31:6443"],
}


def _write(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            yaml.safe_dump(config, handle, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def base_config(cluster: str, token: str, ca_pem: str) -> dict:
    if cluster not in ENDPOINTS:
        raise Rejected(f"unsupported target cluster: {cluster}")
    tls_name = "kube-api.service.re8ch.com" if cluster in {"re8ch", "re8ch-main"} else None
    cluster_data = {
        "server": ENDPOINTS[cluster][0],
        "certificate-authority-data": base64.b64encode(ca_pem.encode()).decode(),
    }
    if tls_name:
        cluster_data["tls-server-name"] = tls_name
    return {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": cluster, "cluster": cluster_data}],
        "users": [{"name": "release-executor", "user": {"token": token}}],
        "contexts": [{"name": "release-executor", "context": {"cluster": cluster, "user": "release-executor"}}],
        "current-context": "release-executor",
    }


def select(path: Path, config: dict, cluster: str) -> str:
    failures = []
    for endpoint in ENDPOINTS.get(cluster, []):
        config["clusters"][0]["cluster"]["server"] = endpoint
        _write(path, config)
        try:
            result = subprocess.run(
                ["kubectl", "--kubeconfig", str(path), "--request-timeout=8s", "get", "--raw=/readyz"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{endpoint} (timeout)")
            continue
        if result.returncode == 0:
            print(f"selected Kubernetes endpoint: {endpoint}")
            return endpoint
        reason = " ".join((result.stderr or "").split())[:240] or f"kubectl exit {result.returncode}"
        failures.append(f"{endpoint} ({reason})")
    raise Rejected("no healthy Kubernetes API endpoint: " + ", ".join(failures))


def configure_from_environment() -> None:
    path = Path(os.environ["KUBECONFIG"])
    cluster = os.environ["TARGET_CLUSTER"]
    token = os.environ["EXECUTOR_TOKEN"]
    ca_pem = os.environ["KUBE_API_CA_PEM"]
    if not token or not ca_pem.strip():
        raise Rejected("missing executor token or Kubernetes API CA")
    config = base_config(cluster, token, ca_pem)
    select(path, config, cluster)


if __name__ == "__main__":
    configure_from_environment()
