import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "operations" / "releases"))
import kube_endpoint


def test_main_endpoint_order_and_tls_identity():
    config = kube_endpoint.base_config("re8ch", "token", "ca")
    assert kube_endpoint.ENDPOINTS["re8ch"] == [
        "https://179.255.126.104:443",
        "https://179.253.231.159:443",
        "https://223.159.210.222:6443",
    ]
    assert config["clusters"][0]["cluster"]["tls-server-name"] == "kube-api.service.re8ch.com"


def test_select_fails_over_and_persists_selected_endpoint(tmp_path, monkeypatch):
    attempts = []

    def run(argv, **kwargs):
        config = yaml.safe_load((tmp_path / "config").read_text())
        assert "token" not in config["users"][0]["user"]
        endpoint = config["clusters"][0]["cluster"]["server"]
        attempts.append(endpoint)
        return SimpleNamespace(returncode=0 if endpoint.endswith("159:443") else 1)

    monkeypatch.setattr(kube_endpoint.subprocess, "run", run)
    config = kube_endpoint.base_config("re8ch", "token", "ca")
    selected = kube_endpoint.select(tmp_path / "config", config, "re8ch")
    assert selected == "https://179.253.231.159:443"
    assert attempts == kube_endpoint.ENDPOINTS["re8ch"][:2]
    persisted = yaml.safe_load((tmp_path / "config").read_text())
    assert persisted["clusters"][0]["cluster"]["server"] == selected
    assert persisted["users"][0]["user"]["token"] == "token"


def test_select_treats_timeout_as_failover(tmp_path, monkeypatch):
    calls = 0

    def run(argv, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise kube_endpoint.subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kube_endpoint.subprocess, "run", run)
    config = kube_endpoint.base_config("re8ch", "token", "ca")
    assert kube_endpoint.select(tmp_path / "config", config, "re8ch") == "https://179.253.231.159:443"
