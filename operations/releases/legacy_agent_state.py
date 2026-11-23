"""Adopt only a signed, proven pre-target-field Atlantic Agent state locally."""
import argparse
import json
import re
import subprocess
from pathlib import Path
import yaml

from operation_materialize import state_configmap_name
from profile import INDEPENDENT_AGENT_BOOTSTRAP, ROOT, independent_agent_bootstrap
from ssa_executor import load_archive
from unified_bundle import canonical, digest, validate_schema


def inputs(configmap, contract):
    if not independent_agent_bootstrap(contract):
        raise ValueError('not the independent Agent recovery contract')
    metadata = configmap['metadata']
    if metadata['name'] != state_configmap_name(INDEPENDENT_AGENT_BOOTSTRAP) or metadata['namespace'] != 'among-clusters':
        raise ValueError('legacy state object is outside the exact target')
    state = json.loads(configmap['data']['accepted-state.json'])
    validate_schema(state, 'release-accepted-state.schema.json')
    if state['releaseId'] != INDEPENDENT_AGENT_BOOTSTRAP or state.get('clusterBindingDigest'):
        raise ValueError('legacy state release or binding mismatch')
    expected = 'oci://ghcr.io/pillars-infra/network-gitops-release/' + INDEPENDENT_AGENT_BOOTSTRAP
    if state['bundleReference'] != expected or not re.fullmatch('sha256:[0-9a-f]{64}', state['appliedDigest']):
        raise ValueError('legacy artifact is outside the exact release repository')
    return state


def adopt(configmap, contract, signatures, bundle, repository=ROOT):
    state = inputs(configmap, contract)
    if 'clusterRef' in state:
        raise ValueError('explicit target fields cannot be adopted')
    manifest, _ = load_archive(bundle)
    if (digest(bundle.read_bytes()) != state['payloadDigest']
            or manifest['releaseId'] != state['releaseId']
            or manifest['inventoryDigest'] != state['inventoryDigest']
            or manifest['inventory'] != state['inventory']):
        raise ValueError('legacy payload does not match accepted state')
    reference = state['bundleReference'].removeprefix('oci://')
    candidates = [item for item in signatures
                  if item.get('critical', {}).get('image', {}).get('docker-manifest-digest') == state['appliedDigest']
                  and item.get('critical', {}).get('identity', {}).get('docker-reference') == reference]
    if not candidates:
        raise ValueError('verified signature does not bind the accepted OCI digest')
    claims = candidates[0].get('optional', {})
    revision = claims.get('githubWorkflowSha', '')
    if not re.fullmatch('[0-9a-f]{40}', revision) or claims.get('githubWorkflowRepository') != 'pillars-infra/network-gitops':
        raise ValueError('verified signature has no exact GitHub source revision')
    relative = 'contracts/' + INDEPENDENT_AGENT_BOOTSTRAP + '.yaml'
    result = subprocess.run(['git', 'show', revision + ':' + relative], cwd=repository,
                            capture_output=True, text=True, check=True)
    previous = yaml.safe_load(result.stdout)
    if (digest(canonical(previous)) != manifest['contractDigest']
            or previous['metadata']['name'] != state['releaseId']
            or previous['spec']['target'] != contract['spec']['target']
            or previous['spec']['inventory']['digest'] != manifest['inventoryDigest']):
        raise ValueError('signed legacy source does not prove this cluster target')
    state['clusterRef'] = 're8ch-atlantic'
    configmap['data']['accepted-state.json'] = json.dumps(state, sort_keys=True, separators=(',', ':'))
    return {'adopted': True, 'clusterRef': state['clusterRef'], 'sourceCommit': revision,
            'previousDigest': state['appliedDigest'], 'stateUID': configmap['metadata'].get('uid')}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['needed', 'reference', 'adopt'])
    p.add_argument('--configmap', type=Path, required=True)
    p.add_argument('--contract', type=Path, required=True)
    p.add_argument('--signatures', type=Path)
    p.add_argument('--bundle', type=Path)
    args = p.parse_args()
    cm = json.loads(args.configmap.read_text())
    contract = yaml.safe_load(args.contract.read_text())
    state = inputs(cm, contract)
    if args.command == 'needed':
        return 0 if 'clusterRef' not in state else 1
    if args.command == 'reference':
        print(state['bundleReference'] + '@' + state['appliedDigest'])
    else:
        evidence = adopt(cm, contract, json.loads(args.signatures.read_text()), args.bundle)
        args.configmap.write_text(json.dumps(cm))
        print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
