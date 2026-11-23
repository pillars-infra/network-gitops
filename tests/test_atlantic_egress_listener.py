"""Follow the actual Mihomo Service hop to the Gateway listener, not its name."""
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).parents[1]


def objects(path):
    return [o for o in yaml.safe_load_all((ROOT / path).read_text()) if o]


def test_atlantic_socks_bridge_cannot_reenter_colocated_cn_exit():
    cohort = objects('releases/networking-helm-among-clusters-agent-among-clusters/resources.yaml')
    gateway = next(o for o in cohort if o['kind'] == 'Deployment' and o['metadata']['name'] == 'among-clusters-gateway')
    container, = gateway['spec']['template']['spec']['containers']
    imports = json.loads(next(e['value'] for e in container['env'] if e['name'] == 'IMPORTS_JSON'))
    route, = [r for r in imports if r['name'] == 'atl-exit']
    listener_port = int(route['listen'].rsplit(':', 1)[1])
    configs = objects('releases/networking-native-mihomo-routing/resources.yaml')
    cm = next(o for o in configs if o['kind'] == 'ConfigMap')
    cn = yaml.safe_load(cm['data']['cn.yaml'])
    cn_exit = yaml.safe_load(cm['data']['exit.yaml'])
    atlantic, = [p for p in cn['proxies'] if p['name'] == 'ATLANTIC']
    assert listener_port != cn_exit['mixed-port'], 'Gateway import must not alias the host-network CN SOCKS socket'
    service = next(o for o in cohort if o['kind'] == 'Service')
    port, = [p for p in service['spec']['ports'] if p['name'] == 'atl-exit']
    assert port['port'] == atlantic['port'] == 1080
    assert port['targetPort'] == listener_port
    declared, = [p for p in container['ports'] if p['name'] == 'atl-exit']
    assert declared['containerPort'] == listener_port
    assert route['sessionOnly'] is True
    assert route['expectedSPIFFEID'] == 'spiffe://atlantic.re8ch.com/cluster/re8ch-atlantic'
    policy = next(o for o in cohort if o['kind'] == 'NetworkPolicy' and o['metadata']['name'] == 'among-clusters-gateway')
    assert any({'protocol': 'TCP', 'port': listener_port} in r.get('ports', [])
               and {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'egress-fabric'}}} in r.get('from', [])
               for r in policy['spec']['ingress']), 'Ingress must permit the actual bridge listener rather than the frontend port'
    source = objects('clusters/re8ch/resources.yaml')
    agent = next(o for o in source if o['kind'] == 'HelmRelease' and o['metadata']['name'] == 'among-clusters-agent')
    assert listener_port not in agent['spec']['values']['gateway']['publicAuthority']['requiredForwardPorts']
