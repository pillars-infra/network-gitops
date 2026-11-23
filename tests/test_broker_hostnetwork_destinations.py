"""Host-network destinations must retain the existing declared service-port scope."""
from pathlib import Path
import yaml

ROOT = Path(__file__).parents[1]


def objects(path):
    return [o for o in yaml.safe_load_all((ROOT / path).read_text()) if o]


def ports(rule):
    return {(int(p['port']), p['protocol']) for group in rule['toPorts']
            for p in group['ports']}


def test_host_network_hub_and_gateway_cover_exact_existing_listener_contract():
    source = objects('clusters/re8ch/resources.yaml')
    native = objects('releases/networking-native-credential-broker/resources.yaml')
    release, = [o for o in source if o['kind'] == 'HelmRelease' and
                o['metadata']['name'] == 'among-clusters-agent']
    imports = release['spec']['values']['gateway']['imports']
    expected_import_ports = {(item['port'], 'TCP') for item in imports
                             if item['name'].endswith('-k8s')}
    assert expected_import_ports == {(22240, 'TCP'), (23768, 'TCP'), (33768, 'TCP')}
    expected = {'among-clusters-broker-imports': expected_import_ports,
                'among-clusters-broker-hub': {(8080, 'TCP')}}
    for name, intended in expected.items():
        original, = [o for o in source if o['kind'] == 'CiliumNetworkPolicy' and
                     o['metadata']['name'] == name]
        rendered, = [o for o in native if o['kind'] == 'CiliumNetworkPolicy' and
                     o['metadata']['name'] == name]
        assert rendered == original
        spec = original['spec']
        assert spec['endpointSelector'] == {'matchLabels': {
            'app.kubernetes.io/name': 'among-clusters-credential-broker'}}
        pod_rule, host_rule = spec['egress']
        assert 'toEndpoints' in pod_rule
        assert set(host_rule) == {'toEntities', 'toPorts'}
        assert host_rule['toEntities'] == ['host', 'remote-node']
        assert ports(pod_rule) == ports(host_rule) == intended
        # Host-network identity must not grant arbitrary host ports or entities.
        assert (443, 'TCP') not in ports(host_rule)
        assert (6443, 'TCP') not in ports(host_rule)
