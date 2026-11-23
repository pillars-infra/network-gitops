#!/usr/bin/env python3
"""Exact networking identity and canonical contract selection."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'pillars-infra/network-gitops'
WORKFLOW = '.github/workflows/static-release.yml'
ENVIRONMENT = 'release-executor-networking'
AUDIENCE = 'https://kube-api.re8ch.com/release-executor-networking'
SIGNER = f'https://github.com/{REPOSITORY}/{WORKFLOW}@refs/heads/main'
EXECUTION_PROFILES = {
    're8ch': {'environment': ENVIRONMENT, 'audience': AUDIENCE},
    're8ch-atlantic': {
        'environment': 'release-executor-networking-atlantic',
        'audience': 'https://kube-api.re8ch.com/release-executor-networking-atlantic',
    },
}

# Manual recovery of the outbound credential producer uses its original,
# independently scoped OIDC identity. Never replay this direct bootstrap path.
INDEPENDENT_AGENT_BOOTSTRAP = 'networking-native-atlantic-among-clusters'

CLOUD_CANARY_RELEASES={
    'networking-native-self-cloud-target-canary':'re8ch',
    'networking-native-atlantic-cloud-target-canary':'re8ch-atlantic',
}

def validate_contract(path, for_execution=False):
    resolved = path.resolve()
    if resolved.parent != ROOT / 'contracts':
        raise ValueError('contract must be directly under contracts')
    contract = yaml.safe_load(resolved.read_text())
    spec = contract['spec']; name = contract['metadata']['name']
    if str(path) != f'contracts/{name}.yaml' or not name.startswith(('networking-native-','networking-helm-')):
        raise ValueError('use canonical networking contract path')
    cluster = spec['target']['cluster']
    if cluster not in EXECUTION_PROFILES:
        raise ValueError('unsupported networking target cluster')
    bound=bool(spec['target'].get('clusterBindingDigest'))
    if bound and not re.fullmatch('[0-9a-f]{64}',spec['target']['clusterBindingDigest']):
        raise ValueError('invalid cluster binding digest')
    if name in CLOUD_CANARY_RELEASES and (CLOUD_CANARY_RELEASES[name]!=cluster or not bound):
        raise ValueError('cloud canary requires its exact reviewed cluster binding')
    bootstrap = (name == INDEPENDENT_AGENT_BOOTSTRAP and cluster == 're8ch-atlantic'
                 and spec['target']['namespace'] == 'among-clusters'
                 and spec['authorization'].get('requireExisting') is True
                 and spec['lifecycle'].get('prune') is False)
    if for_execution and cluster != 're8ch' and not bound and not bootstrap:
        raise ValueError('legacy remote transport is unsupported; a reviewed binding is required')
    execution = EXECUTION_PROFILES['re8ch' if bound else cluster]
    expected = dict(repository=REPOSITORY, workflow=WORKFLOW, ref='refs/heads/main', environment=execution['environment'], audience=execution['audience'], signer=SIGNER, issuer='https://token.actions.githubusercontent.com')
    if spec['authorityDomain'] != 'networking' or spec['provenance'] != expected:
        raise ValueError('unexpected networking execution identity')
    if name.startswith('networking-native-'):
        expected_source=dict(renderer='kustomize', revision='github-main-reviewed', repository=REPOSITORY, path=f'releases/{name}')
    elif name=='networking-helm-advanced-fabric-kube-system':
        expected_source=dict(renderer='kustomize', revision='github-main-reviewed',repository=REPOSITORY,path=f'releases/{name}',protectedHelm='advanced-fabric')
    else:
        ledger=json.loads((ROOT/'operations/releases/helm-authority.json').read_text())
        entry=next((r for r in ledger['releases'] if r['releaseId']==name),None)
        if not entry:raise ValueError('unknown Helm projection')
        expected_source=entry['source']
        rendered=ROOT/f'releases/{name}/resources.yaml'
        if hashlib.sha256(rendered.read_bytes()).hexdigest()!=entry['renderedSHA256']:
            raise ValueError('Helm projection differs from reviewed render')
    if spec['source'] != expected_source:
        raise ValueError('source must be the reviewed projection')
    return {'release-id': name, 'namespace': spec['target']['namespace'], 'cluster':cluster, 'control-cluster':'re8ch' if bound else cluster, 'domain':'networking', 'environment':execution['environment'], 'audience':execution['audience'], 'kubernetes-group':'re8ch:release-executor:networking', 'signer':SIGNER}

REPLAY_WORKFLOW = '.github/workflows/networking-reconcile.yml'
REPLAY_ENVIRONMENT = 'release-reconciler-networking'
REPLAY_AUDIENCE = 'https://kube-api.re8ch.com/release-reconciler-networking'

def replay_provenance(contract):
    spec=contract['spec']
    expected=dict(repository=REPOSITORY,workflow=WORKFLOW,ref='refs/heads/main',environment=ENVIRONMENT,audience=AUDIENCE,signer=SIGNER,issuer='https://token.actions.githubusercontent.com')
    if spec.get('authorityDomain')!='networking' or spec.get('provenance')!=expected:
        return None
    return dict(repository=REPOSITORY,workflow=REPLAY_WORKFLOW,ref='refs/heads/main',environment=REPLAY_ENVIRONMENT,audience=REPLAY_AUDIENCE)

def replay_matrix():
    result=[]
    for path in sorted((ROOT/'contracts').glob('networking-*.yaml')):
        relative=path.relative_to(ROOT)
        profile=validate_contract(relative)
        # Explicit conformance jobs are not persistent desired business services.
        if profile['release-id'] in CLOUD_CANARY_RELEASES:
            continue
        # Only reviewed Cloud bindings can replay remote business requests
        # with the original main identity; legacy direct remote paths are inert.
        if profile['control-cluster'] != 're8ch':
            continue
        # The local Flux namespace was removed; its retained encrypted input
        # cannot have an accepted runtime state to replay.
        if profile['namespace']=='flux-network-system':
            continue
        result.append({**profile,'contract':str(relative),'environment':REPLAY_ENVIRONMENT,'audience':REPLAY_AUDIENCE})
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--contract',type=Path);p.add_argument('--replay-matrix',action='store_true');p.add_argument('--github-output',type=Path);p.add_argument('--for-execution',action='store_true');args=p.parse_args()
    if args.replay_matrix:
        print(json.dumps({'include':replay_matrix()},separators=(',',':')));return
    if args.contract is None:p.error('--contract required')
    value=validate_contract(args.contract,for_execution=args.for_execution)
    if args.github_output:
        with args.github_output.open('a') as f:
            for k,v in value.items():f.write(f'{k}={v}\n')
    else:print(json.dumps(value,sort_keys=True))
if __name__=='__main__':main()
