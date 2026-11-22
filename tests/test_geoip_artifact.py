import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

from test_public_edge_dns_path import router

ROOT = Path(__file__).resolve().parents[1]


def fetcher():
    cm = next(o for o in yaml.safe_load_all((ROOT / 'clusters/re8ch/resources.yaml').read_text())
              if o and o.get('kind') == 'ConfigMap' and o['metadata']['name'] == 'powerdns-cloud-authorities')
    namespace = {'__name__': 'test_fetcher'}
    exec(compile(cm['data']['geoip-fetch.py'], 'geoip-fetch.py', 'exec'), namespace)
    return namespace


def test_verified_database_is_written_atomically(tmp_path, monkeypatch):
    ns = fetcher()
    country = b'country-data-fixture'
    compressed = gzip.compress(country)
    source = {'artifactURL': 'https://github.com/pillars-infra/network-gitops/releases/download/geoip-dbip-country-test/country.gz',
              'sha256': hashlib.sha256(compressed).hexdigest(),
              'databaseSHA256': hashlib.sha256(country).hexdigest()}
    monkeypatch.setattr(ns['urllib'].request, 'urlopen', lambda *args, **kwargs: io.BytesIO(compressed))
    target = tmp_path / 'country.mmdb'
    ns['fetch_to'](source, target)
    assert target.read_bytes() == country
    assert not target.with_suffix('.tmp').exists()
    source['databaseSHA256'] = '0' * 64
    target.write_bytes(b'previous-verified-data')
    with pytest.raises(ValueError, match='database digest mismatch'):
        ns['fetch_to'](source, target)
    assert target.read_bytes() == b'previous-verified-data'


def test_database_origin_is_restricted_before_network_access(tmp_path):
    ns = fetcher()
    with pytest.raises(ValueError, match='unapproved artifact origin'):
        ns['fetch_to']({'artifactURL': 'http://169.254.169.254/'}, tmp_path / 'country.mmdb')


def test_udp_and_tcp_relays_bind_the_declared_source(monkeypatch):
    ns = router(monkeypatch)
    ns['routed'] = lambda packet, ip: (packet, ('127.0.0.2', 53))
    upstream = __import__('unittest.mock', fromlist=['MagicMock']).MagicMock()
    upstream.__enter__.return_value = upstream
    upstream.recvfrom.return_value = (b'answer', ('127.0.0.2', 53))
    monkeypatch.setattr(ns['socket'], 'socket', lambda *args: upstream)
    listener = __import__('unittest.mock', fromlist=['MagicMock']).MagicMock()
    ns['udp_query'](listener, b'question', ('192.0.2.20', 12345))
    upstream.bind.assert_called_once_with(('192.0.2.10', 0))
    listener.sendto.assert_called_once_with(b'answer', ('192.0.2.20', 12345))

    client = __import__('unittest.mock', fromlist=['MagicMock']).MagicMock()
    client.__enter__.return_value = client
    calls = iter([b'\x00\x08', b'question', b'\x00\x06', b'answer'])
    def exact(stream, count):
        try: return next(calls)
        except StopIteration: raise ConnectionError
    ns['read_exact'] = exact
    connect = __import__('unittest.mock', fromlist=['MagicMock']).MagicMock(return_value=upstream)
    monkeypatch.setattr(ns['socket'], 'create_connection', connect)
    ns['tcp_client'](client, '192.0.2.20')
    connect.assert_called_once_with(('127.0.0.2', 53), timeout=3, source_address=('192.0.2.10', 0))
