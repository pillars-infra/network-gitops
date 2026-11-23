"""The existing Among owners expose telemetry without moving public authority."""
from pathlib import Path
from urllib.parse import urlsplit
import yaml

ROOT = Path(__file__).parents[1]
IMAGE = 'ghcr.io/among-clusters/among-clusters@sha256:e4318df4f9f6cc47c391c20f178c4b8000627c69c09cc48364630c4a68853d45'
RELEASE = 'among-clusters@9f57051793c9f5218d1cd0827fa705d54d0bccfd'


def test_existing_hub_and_broker_private_telemetry_contract():
    for namespace, name in [('among-clusters', 'among-clusters-hub'),
                            ('credential-broker', 'among-clusters-credential-broker')]:
        path = ROOT / f'releases/networking-helm-among-clusters-hub-{namespace}/resources.yaml'
        objects = [o for o in yaml.safe_load_all(path.read_text()) if o]
        deployment = next(o for o in objects if o['kind'] == 'Deployment')
        pod = deployment['spec']['template']['spec']
        container, = pod['containers']
        assert container['image'] == IMAGE
        env = {e['name']: e for e in container['env']}
        assert env['POD_IP']['valueFrom']['fieldRef']['fieldPath'] == 'status.podIP'
        assert env['SENTRY_RELEASE']['value'] == RELEASE
        assert env['SENTRY_ENVIRONMENT']['value'] == 'production'
        dsn = urlsplit(env['SENTRY_DSN']['value'])
        assert dsn.scheme == 'https' and dsn.username and not dsn.password
        assert dsn.path == '/4509349088985088' and not dsn.query and not dsn.fragment
        assert not any('AUTH_TOKEN' in e for e in env)
        if namespace == 'among-clusters':
            assert pod['hostNetwork'] is True
            assert pod['dnsPolicy'] == 'ClusterFirstWithHostNet'
            assert next(p for p in container['ports'] if p['name'] == 'http')['hostPort'] == 8080
        service = next(o for o in objects if o['kind'] == 'Service')
        assert service['metadata']['name'] == name
        assert service['metadata']['labels']['app.kubernetes.io/name'] == name
        assert service['spec']['ports'] == [
            {'name': 'http', 'port': 80, 'targetPort': 'http'},
            {'name': 'metrics', 'port': 9090, 'targetPort': 'metrics'}]
        policy = next(o for o in objects if o['kind'] == 'NetworkPolicy')['spec']
        scrape = [r for r in policy['ingress'] if {'port': 9090, 'protocol': 'TCP'} in r['ports']]
        assert scrape == [{'from': [{'namespaceSelector': {'matchLabels': {
            'kubernetes.io/metadata.name': 'observability-system'}}, 'podSelector': {'matchLabels': {
            'app.kubernetes.io/instance': 're8ch', 'app.kubernetes.io/name': 'vmagent'}}}],
            'ports': [{'port': 9090, 'protocol': 'TCP'}]}]
        assert {'ports': [{'port': 443, 'protocol': 'TCP'}], 'to': [
            {'ipBlock': {'cidr': '0.0.0.0/0'}}, {'ipBlock': {'cidr': '::/0'}}]} in policy['egress']
        for route in [o for o in objects if o['kind'] in ('HTTPRoute', 'Ingress')]:
            assert '9090' not in yaml.safe_dump(route)
