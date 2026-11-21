from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def documents():
    return [item for item in yaml.safe_load_all(
        (ROOT / "clusters/re8ch/resources.yaml").read_text()
    ) if item]


def test_powerdns_classifies_location_but_public_edge_selects_candidate():
    config = next(item for item in documents()
                  if item.get("kind") == "ConfigMap"
                  and item.get("metadata", {}).get("name") == "powerdns-cloud-authorities")
    router = config["data"]["dns-router.py"]
    compile(router, "dns-router.py", "exec")
    assert '"PUBLIC_EDGE_MANAGER_DNS_SERVICE_HOST"' in router
    assert 'EDGE = (socket.gethostbyname(EDGE_HOST), 53)' in router
    assert 'return set_ecs(packet, classify(client_ip), replace=True), EDGE' in router

    geo = yaml.safe_load(config["data"]["geoip.yaml"])["domains"][0]
    assert geo["domain"] == "classify.geo.re8ch.internal"
    records = geo["records"]
    assert records["cn.classify.geo.re8ch.internal"] == [{"a": "198.18.1.1"}]
    assert records["us.classify.geo.re8ch.internal"] == [{"a": "198.18.2.1"}]
    assert records["de.classify.geo.re8ch.internal"] == [{"a": "198.18.3.1"}]
    assert records["my.classify.geo.re8ch.internal"] == [{"a": "198.18.4.1"}]


def test_all_atlantic_ingress_points_are_reviewed_api_candidates():
    release = next(item for item in documents()
                   if item.get("kind") == "HelmRelease"
                   and item.get("metadata", {}).get("name") == "public-edge-manager")
    values = release["spec"]["values"]
    candidates = {item["name"]: item for item in values["discovery"]["federatedEdges"]}
    assert {(item["nodeName"], item["area"], item["region"], item["address"])
            for item in candidates.values()} == {
        ("overseas-la", "US-WEST", "us-la-1", "179.255.126.104"),
        ("overseas-la-2", "US-WEST", "us-la-2", "179.253.231.159"),
        ("overseas-flk", "EU-CENTRAL", "de-fsn", "2.28.106.230"),
        ("re8ch-atlantic-server-hel1", "EU-NORTH", "fi-hel1", "2.29.219.31"),
        ("overseas-kl", "SEA", "my-kul", "198.20.153.89"),
    }
    assert all(item["clusterRef"] == "re8ch-atlantic" for item in candidates.values())
    assert all(item["serviceClasses"] == ["api", "db-rw", "web", "service-pilot"]
               for item in candidates.values())
    assert values["image"]["digest"] == (
        "sha256:8d9f78dcf2c904c628f58250d427c8b976e55943ba4650fae87ccbfd0a63a3b0"
    )


def test_public_edge_has_stable_aliases_for_external_cdns_and_access_portal():
    release = next(item for item in documents()
                   if item.get("kind") == "HelmRelease"
                   and item.get("metadata", {}).get("name") == "public-edge-manager")
    services = release["spec"]["values"]["services"]

    assert services["auth-origin.service.re8ch.com."] == {
        "acceptedStatuses": [200],
        "class": "service-pilot",
        "probeHost": "auth-origin.re8ch.com",
        "probePath": "/.well-known/openid-configuration",
        "service": "auth-origin-service",
    }
    assert services["sub-access.service.re8ch.com."] == {
        "acceptedStatuses": [302],
        "class": "service-pilot",
        "probeHost": "sub.access.re8ch.com",
        "probePath": "/",
        "service": "sub-access-service",
    }


def test_external_records_do_not_overlap_managed_services_or_zones():
    release = next(item for item in documents()
                   if item.get("kind") == "HelmRelease"
                   and item.get("metadata", {}).get("name") == "public-edge-manager")
    values = release["spec"]["values"]
    external_records = set(values["dns"]["externalRecords"])
    managed_services = set(values["services"])
    managed_zones = set(values["dns"]["axfrZones"])

    assert external_records.isdisjoint(managed_services)
    assert external_records.isdisjoint(managed_zones)
    assert "kube-api.re8ch.com." not in external_records
    assert "kube-api-backup.re8ch.com." not in external_records
