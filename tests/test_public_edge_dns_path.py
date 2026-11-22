from pathlib import Path
import socket

import yaml

ROOT = Path(__file__).resolve().parents[1]


def router(monkeypatch):
    docs = yaml.safe_load_all((ROOT / 'clusters/re8ch/resources.yaml').read_text())
    cm = next(o for o in docs if o and o.get('kind') == 'ConfigMap'
              and o['metadata']['name'] == 'powerdns-cloud-authorities')
    monkeypatch.setenv('LISTEN_ADDRESS', '192.0.2.10')
    monkeypatch.setenv('PUBLIC_EDGE_MANAGER_DNS_SERVICE_HOST', '127.0.0.1')
    ns = {'__name__': 'test_router'}
    exec(compile(cm['data']['dns-router.py'], 'dns-router.py', 'exec'), ns)
    return ns


def test_provider_and_overlay_receive_both_dns_transports(monkeypatch):
    ns = router(monkeypatch)
    calls = []
    class Listener:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def connect(self, target): pass
        def getsockname(self): return ('198.51.100.10', 10000)
        def setsockopt(self, *args): pass
        def bind(self, target): calls.append(target)
        def listen(self, *args): pass
        def close(self): pass
    monkeypatch.setattr(socket, 'socket', lambda *args: Listener())
    addresses = ns['listener_addresses']()
    assert addresses == ['192.0.2.10', '198.51.100.10']
    assert len(ns['bind_listeners'](addresses)) == 4
    assert calls == [(address, 53) for address in addresses for _ in range(2)]


def test_service_targets_backend_not_frontend_listener():
    docs = list(yaml.safe_load_all((ROOT / 'releases/networking-helm-public-edge-manager-regional-routing/resources.yaml').read_text()))
    ds = next(o for o in docs if o['kind'] == 'DaemonSet' and o['metadata']['name'] == 'public-edge-manager')
    env = {e['name']: e for e in ds['spec']['template']['spec']['containers'][0]['env']}
    assert env['DNS_PORT']['value'] == '1053'
    assert env['BIND_ADDRESS']['valueFrom']['fieldRef']['fieldPath'] == 'status.hostIP'
    svc = next(o for o in docs if o['kind'] == 'Service' and o['metadata']['name'] == 'public-edge-manager-dns')
    assert {(p['protocol'], p['port'], p['targetPort']) for p in svc['spec']['ports']} == {
        ('UDP', 53, 1053), ('TCP', 53, 1053)}


def test_public_queries_do_not_fall_back_to_legacy_axfr_data(monkeypatch):
    ns = router(monkeypatch)
    # No query name or record type may send clients back to the stale BIND zone.
    ns['classify'] = lambda source: '198.18.2.1'
    seen = []
    ns['set_ecs'] = lambda packet, address, replace=False: seen.append((address, replace)) or packet
    for packet in (b'api-query', b'NS-query', b'SOA-query', b'AAAA-query'):
        forwarded, target = ns['routed'](packet, '192.0.2.20')
        assert forwarded == packet
        assert target == ns['EDGE']
        assert target != ns['BIND']
    assert seen == [('198.18.2.1', True)] * 4
