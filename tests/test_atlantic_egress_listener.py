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


def test_atlantic_quic_prefers_reviewed_la_ingress_with_r640_fallback():
    provider = objects('releases/networking-helm-among-clusters-agent-among-clusters/resources.yaml')
    service = next(o for o in provider if o['kind'] == 'Service' and o['metadata']['name'] == 'among-clusters-gateway')
    gateway_port = next(p for p in service['spec']['ports'] if p['name'] == 'gateway')
    assert service['spec']['type'] == 'NodePort'
    assert gateway_port == {'name': 'gateway', 'nodePort': 30443, 'port': 8443,
                            'protocol': 'UDP', 'targetPort': 8443}

    atlantic = objects('releases/networking-native-atlantic-among-clusters/resources.yaml')
    gateway = next(o for o in atlantic if o['kind'] == 'Deployment' and o['metadata']['name'] == 'among-clusters-gateway')
    env = {item['name']: item.get('value') for item in gateway['spec']['template']['spec']['containers'][0]['env']}
    sessions = json.loads(env['PEER_SESSIONS_JSON'])
    assert sessions == [{
        'endpoints': ['179.255.126.104:30443', '179.253.231.159:30443', '223.159.210.222:8443'],
        'expectedSPIFFEID': 'spiffe://re8ch.internal/cluster/re8ch',
    }]

    edge = next(o for o in atlantic if o['kind'] == 'DaemonSet' and o['metadata']['name'] == 'among-clusters-edge')
    relay = next(c for c in edge['spec']['template']['spec']['containers'] if c['name'] == 'main-quic-relay')
    assert relay['image'] == ('docker.io/alpine/socat@'
                              'sha256:beb4a68d9e4fe6b0f21ea774a0fde6c31f580dde6368939ed70100c5385b015e')
    assert relay['args'] == ['UDP4-RECVFROM:30443,fork,reuseaddr',
                             'UDP4-SENDTO:223.159.210.222:8443']
    assert relay['ports'] == [{'name': 'main-quic', 'containerPort': 30443,
                               'hostPort': 30443, 'protocol': 'UDP'}]

    policy = next(o for o in atlantic if o['kind'] == 'NetworkPolicy' and o['metadata']['name'] == 'among-clusters-edge')
    assert any({'protocol': 'UDP', 'port': 30443} in rule.get('ports', [])
               for rule in policy['spec']['ingress'])
    assert any({'ipBlock': {'cidr': '223.159.210.222/32'}} in rule.get('to', [])
               and {'protocol': 'UDP', 'port': 8443} in rule.get('ports', [])
               for rule in policy['spec']['egress'])
