"""Project exact Agent bootstrap facts without publishing credentials or env values."""
import json
import re
import subprocess
import sys

EXPECTED_IMAGE = 'ghcr.io/among-clusters/among-clusters@sha256:27288e43138c052e9804600c512f296832b2037ea9a016e04a08adb4bb024629'


def project(deployment):
    metadata = deployment['metadata']
    if metadata['namespace'] != 'among-clusters' or metadata['name'] != 'among-clusters-agent':
        raise ValueError('unexpected bootstrap object')
    containers = deployment['spec']['template']['spec']['containers']
    if len(containers) != 1:
        raise ValueError('unexpected Agent container layout')
    container = containers[0]
    status = deployment.get('status', {})
    env = {item['name']: item.get('value', '') for item in container.get('env', [])}
    return {'uid': metadata['uid'], 'generation': metadata['generation'],
            'rollout': {key: status.get(key, 0) for key in ['observedGeneration', 'replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas', 'unavailableReplicas']},
            'desiredReplicas': deployment['spec'].get('replicas', 1),
            'reviewedImage': container['image'] == EXPECTED_IMAGE,
            'clusterIdentityMatches': env.get('CLUSTER_ID') == 're8ch-atlantic',
            'brokerConfigured': bool(env.get('BROKER_ENDPOINT')),
            'brokerEndpointMatches': env.get('BROKER_ENDPOINT') == 'https://among-clusters.service.re8ch.com/broker',
            'syncIntervalMatches': env.get('SYNC_INTERVAL') == '5m'}


def classify_logs(value):
    result = []
    for line in value.splitlines():
        category = None
        if 'local customer approval' in line: category = 'local-approval'
        elif 'forbidden' in line.lower(): category = 'kubernetes-authorization'
        elif 'credential broker public key unavailable' in line: category = 'broker-public-key'
        elif 'grant polling requires' in line: category = 'grant-protocol'
        elif 'no such host' in line.lower(): category = 'dns'
        elif any(x in line.lower() for x in ['deadline', 'timeout']): category = 'timeout'
        elif any(x in line.lower() for x in ['connection refused', 'connection reset', 'no route']): category = 'connection'
        elif 'managed access:' in line: category = 'managed-access-error'
        if category:
            item = {'category': category}
            match = re.search(r'(credential broker|hub) returned ([1-5][0-9]{2})', line)
            if match: item.update(upstream=match[1], status=int(match[2]))
            item['resources'] = [x for x in ['kube-root-ca.crt', 'configmaps', 'serviceaccounts/token', 'clusterroles', 'rolebindings', 'secrets'] if x in line]
            result.append(item)
    return result


def observer_facts(runner=subprocess.run):
    # Ask this exact original principal; never grant permission or switch identity.
    def run(args):
        try:
            return runner(['kubectl', '--request-timeout=10s', *args], capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
    permissions = {}
    for key, args in {'pods': ['list', 'pods'], 'logs': ['get', 'pods', '--subresource=log']}.items():
        r = run(['auth', 'can-i', *args, '-n', 'among-clusters'])
        answer = r.stdout.strip() if r else ''
        permissions[key] = answer == 'yes' if answer in {'yes', 'no'} else None
    result = {'observerPermissions': permissions}
    if permissions['pods'] is not True:
        return result
    r = run(['get', 'pods', '-n', 'among-clusters', '-l', 'app.kubernetes.io/name=among-clusters-agent', '-o', 'json'])
    if not r or r.returncode:
        result['podMetadataRead'] = 'failed'
        return result
    pods = []
    for pod in json.loads(r.stdout).get('items', []):
        name = pod['metadata']['name']
        if not re.fullmatch(r'among-clusters-agent-[a-z0-9-]+', name):
            continue
        item = {'name': name, 'uid': pod['metadata']['uid'], 'node': pod.get('spec', {}).get('nodeName'),
                'phase': pod.get('status', {}).get('phase'), 'deleting': bool(pod['metadata'].get('deletionTimestamp')),
                'containers': [{k: c.get(k) for k in ['name', 'ready', 'restartCount', 'imageID']} |
                               {'waitingReason': c.get('state', {}).get('waiting', {}).get('reason'),
                                'terminatedReason': c.get('lastState', {}).get('terminated', {}).get('reason'),
                                'exitCode': c.get('lastState', {}).get('terminated', {}).get('exitCode')}
                               for c in pod.get('status', {}).get('containerStatuses', [])]}
        if permissions['logs'] is True:
            logs = run(['logs', name, '-n', 'among-clusters', '-c', 'agent', '--tail=100', '--since=10m'])
            item['logRead'] = 'success' if logs and not logs.returncode else 'failed'
            if logs and not logs.returncode: item['safeErrors'] = classify_logs(logs.stdout)
        pods.append(item)
    result['pods'] = pods
    return result


if __name__ == '__main__':
    print(json.dumps(project(json.load(sys.stdin)) | observer_facts(), sort_keys=True))
