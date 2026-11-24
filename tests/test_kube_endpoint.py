import sys
import hashlib
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


def test_atlantic_mux_waits_for_fragmented_client_hello():
    manifest = (Path(__file__).resolve().parents[1] / "releases" / "networking-native-atlantic-among-clusters" / "resources.yaml").read_text()
    assert "tcp-request inspect-delay 5s" in manifest
    assert "tcp-request content accept if { req.ssl_hello_type 1 }" in manifest
    assert "reject unless { req.ssl_hello_type 1 }" not in manifest
    objects = list(yaml.safe_load_all(manifest))
    routes = next(obj for obj in objects if obj and obj.get("kind") == "ConfigMap" and obj["metadata"]["name"] == "among-clusters-edge-sni")
    gateway = next(obj for obj in objects if obj and obj.get("kind") == "Deployment" and obj["metadata"]["name"] == "among-clusters-gateway")
    checksum = hashlib.sha256(routes["data"]["haproxy.cfg"].encode()).hexdigest()
    assert gateway["spec"]["template"]["metadata"]["annotations"]["networking.re8ch.com/haproxy-config-sha256"] == checksum


def test_atlantic_stalwart_public_edge_is_local_and_uses_db_rw_sso():
    root = Path(__file__).resolve().parents[1]
    among_objects = list(yaml.safe_load_all((root / "releases/networking-native-atlantic-among-clusters/resources.yaml").read_text()))
    routes = next(obj for obj in among_objects if obj and obj.get("kind") == "ConfigMap" and obj["metadata"]["name"] == "among-clusters-edge-sni")
    assert "use_backend local_stalwart if { req.ssl_sni -i id.re8ch.com }" in routes["data"]["haproxy.cfg"]
    assert "stalwart.mail-system.svc.cluster.local:443" in routes["data"]["haproxy.cfg"]

    mail_objects = list(yaml.safe_load_all((root / "releases/networking-native-atlantic-mail-system/resources.yaml").read_text()))
    certificate = next(obj for obj in mail_objects if obj and obj.get("kind") == "Certificate")
    assert certificate["spec"]["dnsNames"] == ["mail.re8ch.com", "id.re8ch.com"]
    deployment = next(obj for obj in mail_objects if obj and obj.get("kind") == "Deployment" and obj["metadata"]["name"] == "stalwart-webmail")
    env = {item["name"]: item.get("value") for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["OAUTH_CLIENT_ID"] == "705c1168-43d8-4ec3-980a-0327a59c7fc6"
    assert env["OAUTH_ISSUER_URL"] == "https://db-rw.re8ch.com/auth/v1"


def test_select_fails_over_and_persists_selected_endpoint(tmp_path, monkeypatch):
    attempts = []

    def run(argv, **kwargs):
        config = yaml.safe_load((tmp_path / "config").read_text())
        assert config["users"][0]["user"]["token"] == "token"
        endpoint = config["clusters"][0]["cluster"]["server"]
        attempts.append(endpoint)
        return SimpleNamespace(returncode=0 if endpoint.endswith("159:443") else 1, stderr="")

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
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(kube_endpoint.subprocess, "run", run)
    config = kube_endpoint.base_config("re8ch", "token", "ca")
    assert kube_endpoint.select(tmp_path / "config", config, "re8ch") == "https://179.253.231.159:443"


def test_select_reports_bounded_transport_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(
        kube_endpoint.subprocess,
        "run",
        lambda argv, **kwargs: SimpleNamespace(returncode=1, stderr="certificate rejected " * 100),
    )
    config = kube_endpoint.base_config("re8ch-atlantic", "token", "ca")
    try:
        kube_endpoint.select(tmp_path / "config", config, "re8ch-atlantic")
    except Exception as error:
        message = str(error)
    assert "certificate rejected" in message
    assert len(message) < 400
