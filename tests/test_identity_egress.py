from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def identity_egress_deployment(path):
    return next(
        document
        for document in yaml.safe_load_all(path.read_text())
        if document
        and document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("namespace") == "egress-fabric"
        and document.get("metadata", {}).get("name") == "identity-egress"
    )


def assert_schedulable_pod_network_ha(deployment):
    pod = deployment["spec"]["template"]["spec"]
    assert deployment["spec"]["replicas"] == 3
    assert pod["hostNetwork"] is False
    assert pod["dnsPolicy"] == "ClusterFirst"
    assert all(
        "hostPort" not in port
        for container in pod["containers"]
        for port in container.get("ports", [])
    )
    assert pod["affinity"]["podAntiAffinity"] == {
        "preferredDuringSchedulingIgnoredDuringExecution": [
            {
                "weight": 100,
                "podAffinityTerm": {
                    "labelSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "identity-egress",
                        },
                    },
                    "topologyKey": "kubernetes.io/hostname",
                },
            },
        ],
    }
    readiness_path = pod["containers"][0]["readinessProbe"]["httpGet"]["path"]
    assert readiness_path == (
        "/proxies/DIRECT/delay?url=https%3A%2F%2Fapi.github.com&timeout=5000"
    )


def test_identity_egress_source_and_native_projection_own_the_live_ha_repair():
    assert_schedulable_pod_network_ha(
        identity_egress_deployment(ROOT / "clusters/re8ch/resources.yaml")
    )
    assert_schedulable_pod_network_ha(
        identity_egress_deployment(
            ROOT / "releases/networking-native-egress-fabric/resources.yaml"
        )
    )
