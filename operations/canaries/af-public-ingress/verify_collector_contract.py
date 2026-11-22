"""Local fixture-to-collector TLS contract test. No Kubernetes, user credential or runtime apply."""
import argparse
import ast
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
import yaml

parser = argparse.ArgumentParser()
parser.add_argument('--collector-source', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
app = next(document['data']['app.py'] for document in yaml.safe_load_all(
    (root / '00-foundation.yaml').read_text()) if document.get('kind') == 'ConfigMap')
server_ns = {}
exec(compile(app.rsplit('\nThreadingHTTPServer', 1)[0], 'reviewed-canary-app', 'exec'), server_ns)
collector_ns = dict(hashlib=hashlib, ipaddress=ipaddress, json=json, os=os, re=re,
                    socket=socket, ssl=ssl, time=time, NODE='local-contract-test', PLANE='pod', TIMEOUT=1,
                    TLS_MAX_REQUEST_BYTES=8192, TLS_MAX_RESPONSE_BYTES=32768, TLS_MAX_HEADER_BYTES=8192)
functions = {'tls_targets', 'tls_target_configuration_digest', 'tls_transfer'}
source = args.collector_source.read_text()
exec(compile(ast.Module(body=[node for node in ast.parse(source).body
                              if isinstance(node, ast.FunctionDef) and node.name in functions],
                        type_ignores=[]), str(args.collector_source), 'exec'), collector_ns)
with tempfile.TemporaryDirectory() as directory:
    ca, key = Path(directory) / 'test-ca.crt', Path(directory) / 'ephemeral-test.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                    '-out', str(ca), '-subj', '/CN=af-canary.service.re8ch.com', '-addext',
                    'subjectAltName=DNS:af-canary.service.re8ch.com', '-days', '1'], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_alpn_protocols(['http/1.1'])
    context.load_cert_chain(str(ca), str(key))
    server = ThreadingHTTPServer(('127.0.0.1', 0), server_ns['Handler'])
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results = []
    try:
        base = dict(name='fixture', targetService='spiffe://re8ch.internal/ns/af-canary/service/af-ingress-canary',
                    endpoint='127.0.0.1', port=server.server_port, serverName='af-canary.service.re8ch.com',
                    caFile=str(ca), required=True, sourceNodes=['local-contract-test'], path='/transfer')
        target = collector_ns['tls_targets'](json.dumps([base]))[0]
        for padding in [0, 2048]:
            result = collector_ns['tls_transfer'](target, padding, time.monotonic() + 2)
            assert result['success'], result
            assert result['bodyBytes'] == 16384 and result['responseBytes'] < 32768, result
            results.append({'mode': 'normal', 'paddingBytes': padding, 'success': True,
                            'bodyBytes': result['bodyBytes'], 'responseBytes': result['responseBytes']})
        stalled = collector_ns['tls_targets'](json.dumps([{**base, 'path': '/stalled-body', 'timeoutSeconds': .25}]))[0]
        result = collector_ns['tls_transfer'](stalled, 2048, time.monotonic() + 1)
        assert not result['success'] and result['category'] == 'deadline', result
        results.append({'mode': 'stalled-body', 'success': False, 'category': result['category']})
    finally:
        server.shutdown()
        server.server_close()
print(json.dumps({'scope': 'local actual fixture / strict collector integration, not cluster acceptance',
                  'collectorSourceSHA256': hashlib.sha256(source.encode()).hexdigest(), 'cases': results}, indent=2))
