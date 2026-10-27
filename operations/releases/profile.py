#!/usr/bin/env python3
"""Exact networking identity and canonical contract selection."""
import argparse
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'pillars-infra/network-gitops'
WORKFLOW = '.github/workflows/static-release.yml'
ENVIRONMENT = 'release-executor-networking'
AUDIENCE = 'https://kube-api.re8ch.com/release-executor-networking'
SIGNER = f'https://github.com/{REPOSITORY}/{WORKFLOW}@refs/heads/main'

def validate_contract(path):
    resolved = path.resolve()
    if resolved.parent != ROOT / 'contracts':
        raise ValueError('contract must be directly under contracts')
    contract = yaml.safe_load(resolved.read_text())
    spec = contract['spec']; name = contract['metadata']['name']
    if str(path) != f'contracts/{name}.yaml' or not name.startswith('networking-native-'):
        raise ValueError('use canonical networking contract path')
    expected = dict(repository=REPOSITORY, workflow=WORKFLOW, ref='refs/heads/main', environment=ENVIRONMENT, audience=AUDIENCE, signer=SIGNER, issuer='https://token.actions.githubusercontent.com')
    if spec['authorityDomain'] != 'networking' or spec['provenance'] != expected:
        raise ValueError('unexpected networking execution identity')
    if spec['source'] != dict(renderer='kustomize', revision='github-main-reviewed', repository=REPOSITORY, path=f'releases/{name}'):
        raise ValueError('source must be the reviewed native projection')
    return {'release-id': name, 'namespace': spec['target']['namespace'], 'domain':'networking', 'environment':ENVIRONMENT, 'audience':AUDIENCE, 'kubernetes-group':'re8ch:release-executor:networking', 'signer':SIGNER}

def main():
    p=argparse.ArgumentParser();p.add_argument('--contract',type=Path,required=True);p.add_argument('--github-output',type=Path);args=p.parse_args()
    value=validate_contract(args.contract)
    if args.github_output:
        with args.github_output.open('a') as f:
            for k,v in value.items():f.write(f'{k}={v}\n')
    else:print(json.dumps(value,sort_keys=True))
if __name__=='__main__':main()
