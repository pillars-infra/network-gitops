from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def documents():
    return [
        item
        for item in yaml.safe_load_all(
            (ROOT / "clusters/re8ch/resources.yaml").read_text()
        )
        if item
    ]


def test_overseas_flk_hosts_a_local_advanced_fabric_dns_replica():
    release = next(
        item
        for item in documents()
        if item["kind"] == "HelmRelease"
        and item["metadata"]["name"] == "advanced-fabric"
    )
    dns = release["spec"]["values"]["advancedFabric"]["dns"]
    hostnames = dns["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]["nodeSelectorTerms"][0]["matchExpressions"][0]["values"]

    assert dns["replicas"] == 4
    assert "overseas-flk" in hostnames
    assert "mubao-wsl" not in hostnames


def test_legacy_kube_dns_vip_prefers_the_node_local_backend():
    service = next(
        item
        for item in documents()
        if item["kind"] == "Service"
        and item["metadata"].get("namespace") == "kube-system"
        and item["metadata"]["name"] == "kube-dns"
    )

    assert service["spec"]["clusterIP"] == "10.43.0.10"
    assert service["spec"]["trafficDistribution"] == "PreferSameNode"
    assert service["spec"]["internalTrafficPolicy"] == "Cluster"
    assert service["spec"]["selector"] == {
        "app.kubernetes.io/name": "advanced-fabric-doh"
    }
