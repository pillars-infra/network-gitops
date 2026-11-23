"""Project exact Agent bootstrap facts without publishing credentials or env values."""
import json
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


if __name__ == '__main__':
    print(json.dumps(project(json.load(sys.stdin)), sort_keys=True))
