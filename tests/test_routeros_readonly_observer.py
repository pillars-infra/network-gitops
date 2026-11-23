from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import types
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]

def module():
    cm = next(o for o in yaml.safe_load_all((ROOT / 'clusters/re8ch/routeros-public-forward-controller.yaml').read_text()) if o and o['kind'] == 'ConfigMap')
    m = types.ModuleType('observer')
    exec(compile(cm['data']['observe.py'], 'observe.py', 'exec'), m.__dict__)
    return m


class Router:
    def __init__(self):
        self.calls = []

    def request(self, path, method, body=None):
        self.calls.append((path, method, body))
        assert method == 'GET' and body is None
        parsed = urlsplit(path)
        if parsed.path == '/ip/route':
            return [
                {'dst-address': '10.68.9.0/24', 'gateway': '192.168.88.251', 'active': 'true', 'comment': 'private text'},
                {'dst-address': '0.0.0.0/0', 'gateway': '223.159.210.221', 'active': 'true'},
                {'dst-address': '10.68.12.0/24', 'gateway': 'irrelevant'},
            ]
        if parsed.path == '/ip/firewall/nat':
            return [
                {'chain': 'srcnat', 'action': 'masquerade', 'src-address': '10.68.0.0/16', 'comment': 'NEVER PRINT', 'password': 'NEVER PRINT'},
                {'chain': 'srcnat', 'action': 'accept', 'src-address': '!192.168.0.0/16'},
                {'chain': 'srcnat', 'action': 'accept', 'src-address': '10.68.12.0/24', 'dst-address': '10.68.8.0/24'},
                {'chain': 'srcnat', 'action': 'drop', 'disabled': 'true'},
                {'chain': 'dstnat', 'action': 'dst-nat', 'dst-port': '80,443,6443'},
            ]
        assert parsed.path == '/ip/firewall/connection'
        query = parse_qs(parsed.query)
        assert query['src-address'] == ['10.68.9.236:44482']
        assert query['dst-address'] == ['101.34.217.95:53']
        assert query['protocol'] == ['udp']
        return [
            {'src-address': '10.68.9.236:44482', 'dst-address': '101.34.217.95:53', 'protocol': 'udp', 'seen-reply': 'true', 'srcnat': 'true', 'token': 'NEVER PRINT'},
            {'src-address': 'other tenant', 'dst-address': 'private', 'protocol': 'tcp', 'secret': 'NEVER PRINT'},
        ]


def test_real_owner_readonly_projection_and_exact_connection_scope():
    m = module()
    router = Router()
    result = m.observe(router, '10.68.9.236', '101.34.217.95', 44482)
    assert len(router.calls) == 3
    assert len(result['routesCoveringSource']) == 2
    assert len(result['possibleNatRulesInOrder']) == 2
    assert result['unknownNatSelectors'] == 1
    assert result['exactUdpConnections'][0]['seen-reply'] == 'true'
    assert len(result['exactUdpConnections']) == 1
    assert 'NEVER PRINT' not in str(result)
    assert 'other tenant' not in str(result)
    assert all('comment' not in str(row) for row in result['possibleNatRulesInOrder'])


@pytest.mark.parametrize('source,destination,port', [
    ('10.68.12.1', '101.34.217.95', 44482),
    ('10.68.9.236', '8.8.8.8', 44482),
    ('10.68.9.236', '101.34.217.95', 53),
    ('example.com', '101.34.217.95', 44482),
])
def test_unreviewed_scope_cannot_reach_provider(source, destination, port):
    m = module()
    router = Router()
    with pytest.raises(ValueError):
        m.observe(router, source, destination, port)
    assert router.calls == []


def test_absent_connection_is_not_success_or_replayed_probe():
    m = module()
    router = Router()
    original = router.request
    router.request = lambda path, method, body=None: [] if path.startswith('/ip/firewall/connection?') else original(path, method, body)
    result = m.observe(router, '10.68.9.236', '101.34.217.95', 44482)
    assert result['connectionObservation'] == 'absent-or-expired'
    assert result['exactUdpConnections'] == []


def test_bad_provider_shape_does_not_claim_empty_observation():
    m = module()
    router = Router()
    router.request = lambda path, method, body=None: {'password': 'NEVER PRINT'}
    with pytest.raises(ValueError, match='unexpected RouterOS response shape'):
        m.observe(router, '10.68.9.236', '101.34.217.95', 44482)


def test_diagnostic_addition_does_not_change_writer_or_credential_contract():
    docs = list(yaml.safe_load_all((ROOT / 'clusters/re8ch/routeros-public-forward-controller.yaml').read_text()))
    deployment = next(d for d in docs if d and d['kind'] == 'Deployment')
    spec = deployment['spec']['template']['spec']
    assert spec['containers'][0]['command'] == ['python3', '/config/reconcile.py']
    assert next(v for v in spec['volumes'] if v['name'] == 'credential')['secret']['secretName'] == 'mikrotik-routeros-admin'
    assert 'observe.py' not in str(spec['containers'][0]['command'])
