#!/usr/bin/env python3
from pathlib import Path
import hashlib
import ipaddress
import json
import sys
import yaml

root = Path(__file__).resolve().parents[1]
policy = yaml.safe_load((root / "policies/domain.yaml").read_text())
documents = [d for d in yaml.safe_load_all((root / "clusters/re8ch/resources.yaml").read_text()) if d]
pool_documents = [d for d in yaml.safe_load_all(
    (root / "clusters/re8ch/multi-pool/pools.yaml").read_text()) if d]
cilium_release_documents = [d for d in yaml.safe_load_all(
    (root / "clusters/re8ch/cilium-release.yaml").read_text()) if d]
r640_documents = [d for d in yaml.safe_load_all(
    (root / "clusters/re8ch/r640-cilium-datapath.yaml").read_text()) if d]
seen = set()
errors = []
for doc in documents:
    meta = doc.get("metadata", {})
    identity = (doc.get("apiVersion"), doc.get("kind"), meta.get("namespace", ""), meta.get("name"))
    if identity in seen:
        errors.append(f"duplicate object: {identity}")
    seen.add(identity)
for item in policy.get("forbidden", []):
    identity = (item["apiVersion"], item["kind"], item.get("namespace", ""), item["name"])
    if identity in seen:
        errors.append(f"product-owned object is forbidden: {identity}")
fabric_config = next((doc for doc in documents
                      if doc.get("kind") == "ConfigMap"
                      and doc.get("metadata", {}).get("namespace") == "kube-system"
                      and doc.get("metadata", {}).get("name") == "podcidr-fabric-reconciler"), None)
fabric_script = (fabric_config or {}).get("data", {}).get("reconcile.sh", "")
if not fabric_script.startswith("ENC[AES256_GCM,") and fabric_script.count("refresh_cilium_nodes_or_reload\n") < 3:
    errors.append("PodCIDR fabric must refresh Multi-Pool allocations in relay and owner loops")
if not fabric_script.startswith("ENC[AES256_GCM,") and "retaining last-known-good allocations" not in fabric_script:
    errors.append("PodCIDR fabric must retain the last valid CiliumNode allocation map")
if not fabric_script.startswith("ENC[AES256_GCM,") and "exec /bin/sh /config/reconcile.sh" not in fabric_script:
    errors.append("PodCIDR fabric must reload BGP and WireGuard state when allocations change")
fabric_daemonset = next((doc for doc in documents
                         if doc.get("kind") == "DaemonSet"
                         and doc.get("metadata", {}).get("namespace") == "kube-system"
                         and doc.get("metadata", {}).get("name") == "podcidr-fabric-reconciler"), None)
fabric_revision = (((fabric_daemonset or {}).get("spec", {}).get("template", {})
                    .get("metadata", {}).get("annotations", {}))
                   .get("networking.re8ch.com/config-revision"))
if fabric_revision != "multipool-relay-v17":
    errors.append("PodCIDR fabric rollout token does not load the Mubao Multi-Pool relay authority")
if "mubao-wsl" not in (((fabric_daemonset or {}).get("spec", {}).get("template", {})
                          .get("spec", {}).get("affinity", {}).get("nodeAffinity", {})
                          .get("requiredDuringSchedulingIgnoredDuringExecution", {})
                          .get("nodeSelectorTerms", [{}])[0].get("matchExpressions", [{}])[0]
                          .get("values", []))):
    errors.append("PodCIDR fabric must schedule its relay reconciler on mubao-wsl")
for marker in ("10.64.0.0/12", "reconcile_relay_fabric", "re8ch_multipool_relay"):
    if not fabric_script.startswith("ENC[AES256_GCM,") and marker not in fabric_script:
        errors.append(f"PodCIDR fabric is missing Multi-Pool relay marker: {marker}")
fabric_inventory = next((doc for doc in documents
                         if doc.get("kind") == "ConfigMap"
                         and doc.get("metadata", {}).get("namespace") == "kube-system"
                         and doc.get("metadata", {}).get("name") == "podcidr-fabric-inventory"), None)
if not (fabric_inventory or {}).get("data", {}).get("inventory.json", "").startswith("ENC[AES256_GCM,"):
    try:
        fabric_nodes = json.loads((fabric_inventory or {}).get("data", {}).get("inventory.json", "{}"))["nodes"]
        muaya = next(node for node in fabric_nodes if node["name"] == "muaya-ecs")
        if (muaya.get("internalIp"), muaya.get("kubernetesNodeIp"), muaya.get("acceleratedIp")) != (
                "10.181.22.95", "10.250.0.95", "10.250.0.95"):
            errors.append("muaya must retain ZeroTier routing while registering through AdvFab")
    except (KeyError, StopIteration, TypeError, ValueError):
        errors.append("muaya AdvFab migration inventory is missing or invalid")
cluster_inventory = next((doc for doc in documents
                          if doc.get("kind") == "ConfigMap"
                          and doc.get("metadata", {}).get("name") == "cluster-node-inventory"), None)
if (cluster_inventory or {}).get("metadata", {}).get("namespace") != "flux-network-system":
    errors.append("Advanced Fabric values must be owned inside the autonomous Flux namespace")
public_edge = next((doc for doc in documents
                    if doc.get("kind") == "HelmRelease"
                    and doc.get("metadata", {}).get("name") == "public-edge-manager"), None)
public_edge_inventory = (((public_edge or {}).get("spec", {}).get("values", {})
                          .get("discovery", {}).get("clusterInventoryConfigMap", {})))
if public_edge_inventory != {
        "key": "nodes.json", "name": "cluster-node-inventory", "namespace": "flux-network-system"}:
    errors.append("Public Edge must consume the autonomous Network Flux inventory")
address_plan = yaml.safe_load((root / "policies/address-pools.yaml").read_text())
spec = address_plan["spec"]
aggregate = ipaddress.ip_network(spec["aggregate"])
pools = []
defaults = 0
for item in spec["pools"]:
    network = ipaddress.ip_network(item["cidr"])
    if not network.subnet_of(aggregate):
        errors.append(f"pool outside aggregate: {item['name']}/{network}")
    if any(network.overlaps(existing) for existing in pools):
        errors.append(f"overlapping pool: {item['name']}/{network}")
    pools.append(network)
    defaults += int(bool(item.get("default")))
declared = {
    item["metadata"]["name"]: item["spec"]["ipv4"]
    for item in pool_documents
    if item.get("kind") == "CiliumPodIPPool"
}
planned = {item["name"]: item["cidr"] for item in spec["pools"]}
if set(declared) != set(planned):
    errors.append("declared CiliumPodIPPools do not match the address plan")
for name, cidr in planned.items():
    actual = declared.get(name, {})
    if actual.get("cidrs") != [cidr] or actual.get("maskSize") != 24:
        errors.append(f"pool declaration drift: {name}")
if defaults != 1:
    errors.append("exactly one default pool is required")
if int(spec["allocationMaskSize"]) != 24:
    errors.append("allocationMaskSize must remain /24")
if any(network.overlaps(ipaddress.ip_network(old)) for network in pools
       for old in spec.get("compatibilityCIDRs", [])):
    errors.append("new pool overlaps a compatibility CIDR")

lock = yaml.safe_load((root / "releases/lock.yaml").read_text())
if lock.get("cutoverState") != "cilium-root-fix-complete":
    errors.append("Cilium Gateway recovery must remain recorded as complete")
chart_path = root / "charts/cilium-1.21.0-dev.tgz"
chart_digest = hashlib.sha256(chart_path.read_bytes()).hexdigest()
if chart_digest != lock.get("ciliumChartSha256"):
    errors.append("vendored Cilium chart digest does not match releases/lock.yaml")
cilium_release = next((doc for doc in cilium_release_documents
                       if doc.get("kind") == "HelmRelease"
                       and doc.get("metadata", {}).get("name") == "cilium"), None)
cilium_spec = (cilium_release or {}).get("spec", {})
if (cilium_spec.get("releaseName"), cilium_spec.get("targetNamespace"),
        cilium_spec.get("storageNamespace")) != ("cilium", "kube-system", "kube-system"):
    errors.append("Cilium HelmRelease must adopt the existing kube-system/cilium release")
if (((cilium_spec.get("chart") or {}).get("spec") or {}).get("chart")
        != "./charts/cilium-1.21.0-dev.tgz"):
    errors.append("Cilium HelmRelease must use the vendored, digest-locked chart")
cilium_values = cilium_spec.get("values", {})
chart_spec = ((cilium_spec.get("chart") or {}).get("spec") or {})
if chart_spec.get("reconcileStrategy") != "ChartVersion":
    errors.append("Cilium chart reconciliation must not follow every Git revision")
if cilium_values.get("rollOutCiliumPods") is not False:
    errors.append("Cilium agents must not roll on every Helm reconciliation")
upgrade_policy = cilium_spec.get("upgrade") or {}
if upgrade_policy.get("disableWait") is not True:
    errors.append("Cilium Helm upgrades must not be blocked by an offline worker")
if (upgrade_policy.get("remediation") or {}).get("retries") != 0:
    errors.append("Cilium Helm upgrades must not roll the cluster repeatedly on node readiness failure")
operator_image = ((cilium_values.get("operator") or {}).get("image") or {})
if operator_image.get("tag") != lock.get("ciliumOperatorCommit"):
    errors.append("Cilium operator tag is not locked to the deterministic Gateway commit")
if operator_image.get("genericDigest") != lock.get("ciliumOperatorDigest"):
    errors.append("Cilium operator image digest does not match releases/lock.yaml")
if (cilium_values.get("bpf") or {}).get("masquerade") is not False:
    errors.append("global BPF masquerade must remain unchanged during the R640 canary")

r640_config = next((doc for doc in r640_documents
                    if doc.get("kind") == "CiliumNodeConfig"
                    and doc.get("metadata", {}).get("name") == "r640-xdp-native"), None)
r640_defaults = ((r640_config or {}).get("spec") or {}).get("defaults", {})
if r640_defaults.get("bpf-lb-acceleration") != "native":
    errors.append("R640 must retain native XDP acceleration")
if r640_defaults.get("enable-bpf-masquerade") != "true":
    errors.append("R640 must use eBPF masquerading instead of the iptables proxy-return workaround")
if r640_defaults.get("devices") != "eno2np1":
    errors.append("R640 eBPF masquerade must use the authoritative eno2np1 device")
if r640_defaults.get("egress-masquerade-interfaces") != "":
    errors.append("R640 must explicitly clear the inherited legacy egress masquerade interface")
if r640_defaults.get("direct-routing-device") != "eno2np1":
    errors.append("R640 direct routing must remain bound to eno2np1")

cluster_root = yaml.safe_load((root / "clusters/re8ch/kustomization.yaml").read_text())
cluster_resources = set(cluster_root.get("resources", []))
if "routeros-public-forward-controller.yaml" not in cluster_resources:
    errors.append("production root must reconcile the RouterOS public forward controller")
if "kube-api-observer-proxy.yaml" not in cluster_resources:
    errors.append("production root must reconcile the credential-free kube API proxy")
if "kube-api-overseas-relay.yaml" not in cluster_resources:
    errors.append("production root must reconcile the overseas kube API relay")
kube_api_documents = [d for d in yaml.safe_load_all(
    (root / "clusters/re8ch/kube-api-public.yaml").read_text()) if d]
kube_api_route = next((doc for doc in kube_api_documents if doc.get("kind") == "TCPRoute"), None)
kube_api_backends = (((kube_api_route or {}).get("spec", {}).get("rules") or [{}])[0]
                     .get("backendRefs", []))
if kube_api_backends != [{"name": "kube-api-observer-proxy", "port": 6443}]:
    errors.append("public kube API TCPRoute must terminate its transport at the local observer proxy")
api_https_route = next((doc for doc in kube_api_documents if doc.get("kind") == "TLSRoute"
                        and doc.get("metadata", {}).get("name") == "kube-api-https"), None)
if ((api_https_route or {}).get("spec", {}).get("hostnames") != ["kube-api.re8ch.com"] or
        (api_https_route or {}).get("spec", {}).get("parentRefs") !=
        [{"name": "re8ch-gateway-canary", "sectionName": "kube-api-https"}] or
        ((api_https_route or {}).get("spec", {}).get("rules") or [{}])[0].get("backendRefs") !=
        [{"name": "kube-api-observer-proxy", "port": 6443}]):
    errors.append("public kube API TLSRoute must pass only the reviewed hostname to the observer proxy")
gateway_patch = yaml.safe_load((root / "clusters/re8ch/gateway-kube-api-patch.yaml").read_text())
api_https_listener = next((op.get("value") for op in gateway_patch
                           if op.get("value", {}).get("name") == "kube-api-https"), None)
if api_https_listener != {"name": "kube-api-https", "hostname": "kube-api.re8ch.com",
                          "protocol": "TLS", "port": 443, "tls": {"mode": "Passthrough"},
                          "allowedRoutes": {"namespaces": {"from": "Same"}}}:
    errors.append("public kube API 443 listener must be hostname-scoped TLS passthrough")
if any(doc.get("kind") == "ReferenceGrant" for doc in kube_api_documents):
    errors.append("public kube API route must not retain the obsolete cross-namespace grant")
if any(doc.get("kind") == "Ingress" for doc in kube_api_documents):
    errors.append("domestic kube API DNS authority must be retired after overseas relay cutover")
proxy_documents = [d for d in yaml.safe_load_all(
    (root / "clusters/re8ch/kube-api-observer-proxy.yaml").read_text()) if d]
proxy_deployment = next((doc for doc in proxy_documents if doc.get("kind") == "Deployment"), None)
proxy_pod_spec = ((proxy_deployment or {}).get("spec", {}).get("template", {}).get("spec", {}))
proxy_revision = (((proxy_deployment or {}).get("spec", {}).get("template", {})
                   .get("metadata", {}).get("annotations", {}))
                  .get("networking.re8ch.com/config-revision"))
if proxy_revision != "observer-proxy-v2":
    errors.append("kube API observer proxy must roll out half-close-safe transport")
if proxy_pod_spec.get("automountServiceAccountToken") is not False:
    errors.append("kube API observer proxy must not mount a ServiceAccount token")
if proxy_pod_spec.get("nodeSelector") != {"kubernetes.io/hostname": "r640"}:
    errors.append("kube API observer proxy must remain on the public-authority node")
relay_documents = [d for d in yaml.safe_load_all(
    (root / "clusters/re8ch/kube-api-overseas-relay.yaml").read_text()) if d]
relay_deployment = next((doc for doc in relay_documents if doc.get("kind") == "Deployment"), None)
relay_pod_spec = ((relay_deployment or {}).get("spec", {}).get("template", {}).get("spec", {}))
if relay_pod_spec.get("automountServiceAccountToken") is not False:
    errors.append("overseas kube API relay must not mount a ServiceAccount token")
if relay_pod_spec.get("hostNetwork") is not True:
    errors.append("overseas kube API relay must bind the selected node public port")
if relay_pod_spec.get("nodeSelector") != {"kubernetes.io/hostname": "overseas-flk"}:
    errors.append("overseas kube API relay must remain on the reviewed external edge")
relay_containers = relay_pod_spec.get("containers", [])
relay_ports = (relay_containers[0].get("ports", []) if len(relay_containers) == 1 else [])
if relay_ports != [{"name": "kube-api", "containerPort": 6443,
                   "hostPort": 6443, "protocol": "TCP"}]:
    errors.append("overseas kube API relay must expose only host TCP 6443")
relay_service = next((doc for doc in relay_documents if doc.get("kind") == "Service"), None)
relay_annotations = (relay_service or {}).get("metadata", {}).get("annotations", {})
if relay_annotations.get("external-dns.alpha.kubernetes.io/hostname") != "kube-api.re8ch.com":
    errors.append("overseas kube API relay must own the observer hostname")
if relay_annotations.get("external-dns.alpha.kubernetes.io/endpoints-type") != "NodeExternalIP":
    errors.append("observer DNS must derive its target from Kubernetes Node status")
if "external-dns.alpha.kubernetes.io/target" in relay_annotations:
    errors.append("observer DNS must not duplicate a node public IP in static YAML")
external_dns_patch = yaml.safe_load((root / "clusters/re8ch/external-dns-control-api.yaml").read_text())
external_dns_containers = (((external_dns_patch.get("spec") or {}).get("template") or {})
                           .get("spec", {}).get("containers", []))
external_dns_args = external_dns_containers[0].get("args", []) if external_dns_containers else []
if "--source=service" not in external_dns_args:
    errors.append("ExternalDNS must discover the observer relay headless Service")
public_forward_documents = [d for d in yaml.safe_load_all(
    (root / "clusters/re8ch/routeros-public-forward-controller.yaml").read_text()) if d]
public_forward_config = next((doc for doc in public_forward_documents
                              if doc.get("kind") == "ConfigMap"
                              and doc.get("metadata", {}).get("name") ==
                              "routeros-public-forward-controller"), None)
public_forward_deployment = next((doc for doc in public_forward_documents
                                  if doc.get("kind") == "Deployment"
                                  and doc.get("metadata", {}).get("name") ==
                                  "routeros-public-forward-controller"), None)
public_forward_revision = (((public_forward_deployment or {}).get("spec", {}).get("template", {})
                            .get("metadata", {}).get("annotations", {}))
                           .get("networking.re8ch.com/config-revision"))
if public_forward_revision != "kube-api-return-v2":
    errors.append("RouterOS public forward controller must roll out its current config revision")
try:
    public_forward_spec = json.loads((public_forward_config or {}).get("data", {}).get("desired.json", "{}"))
    if public_forward_spec.get("forwards") != [
            {"protocol": "tcp", "port": "6443", "toPort": "6443"}]:
        errors.append("RouterOS public forwards must include only the reviewed kube-api rule")
    if public_forward_spec.get("gatewayVip") != "10.251.0.4":
        errors.append("RouterOS kube-api forward must target the Cilium Gateway VIP")
    if public_forward_spec.get("returnAnchorComment") != "defconf: masquerade after symmetric rules":
        errors.append("RouterOS kube-api return must precede the default masquerade rule")
except (TypeError, ValueError):
    errors.append("RouterOS public forward declaration is invalid")
if "cilium-gateway-cec-update-freeze.yaml" in cluster_resources:
    errors.append("the temporary CEC update freeze must not remain in desired state")
if (root / "clusters/re8ch/cilium-gateway-cec-update-freeze.yaml").exists():
    errors.append("the temporary CEC update freeze manifest must be removed")
if "r640-gateway-proxy-return-guard.yaml" in cluster_resources:
    errors.append("the temporary R640 proxy-return iptables guard must not remain in desired state")
if (root / "clusters/re8ch/r640-gateway-proxy-return-guard.yaml").exists():
    errors.append("the temporary R640 proxy-return iptables guard manifest must be removed")
# Public checks validate encrypted envelopes; content invariants require an
# authorized decrypted checkout. The private archive retains the original tests.
restricted_keys = {"nodes.json", "inventory.json", "advanced-fabric-values.yaml",
                   "adoption.json", "host-network-contract.json", "routeros-transit.json"}
for document in documents:
    if document.get("kind") != "ConfigMap":
        continue
    data = document.get("data", {})
    required = restricted_keys.intersection(data)
    if document.get("metadata", {}).get("name") == "podcidr-fabric-reconciler":
        required.add("reconcile.sh")
    if document.get("metadata", {}).get("name", "").startswith(("control-transit-controller-", "host-network-controller-")):
        required.add("package.json")
    required.update({
        "control-transit-controller-98df2kft25": {"agent.py", "control_pod_mesh.py"},
        "host-network-controller-679588ggt2": {"agent.py"},
        "routeros-transit-controller-m4d4tm44fd": {"routeros_transit.py"},
    }.get(document.get("metadata", {}).get("name"), set()))
    if required:
        if not document.get("sops", {}).get("age") or not document.get("sops", {}).get("mac", "").startswith("ENC[AES256_GCM,"):
            errors.append("restricted ConfigMap must have an authenticated SOPS envelope")
        for key in required:
            if not isinstance(data.get(key), str) or not data[key].startswith("ENC[AES256_GCM,"):
                errors.append(f"restricted ConfigMap key must be encrypted: {key}")
        try:
            digests = json.loads(document["metadata"]["annotations"]["security.re8ch.com/restricted-data-sha256"])
            if any(key not in digests or len(digests[key]) != 64 for key in required):
                errors.append("restricted data requires plaintext parity digests")
        except (KeyError, TypeError, ValueError):
            errors.append("restricted data parity metadata is missing")
for document in documents:
    if document.get("kind") == "HelmRelease" and document.get("metadata", {}).get("name") == "advanced-fabric":
        control_api = document.get("spec", {}).get("values", {}).get("advancedFabric", {}).get("controlPlaneApi", {})
        def encrypted_leaves(value):
            if isinstance(value, dict):
                return all(encrypted_leaves(item) for item in value.values())
            if isinstance(value, list):
                return all(encrypted_leaves(item) for item in value)
            return isinstance(value, str) and value.startswith("ENC[AES256_GCM,")
        if not control_api or not encrypted_leaves(control_api) or not document.get("sops", {}).get("age"):
            errors.append("restricted control-plane matrix must be SOPS encrypted")
if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"validated {policy['domain']}: {len(documents)} objects, {len(pools)} address pools")
