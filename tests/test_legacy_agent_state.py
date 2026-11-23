import copy
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "operations/releases"))

import legacy_agent_state as recovery
import operation_materialize as materialize
from unified_bundle import canonical, compile_bundle, digest

ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path, previous_target=None):
    contract = yaml.safe_load((ROOT / ('contracts/' + recovery.INDEPENDENT_AGENT_BOOTSTRAP + '.yaml')).read_text())
    previous = copy.deepcopy(contract)
    if previous_target:
        previous['spec']['target']['cluster'] = previous_target
    rendered = (ROOT / ('releases/' + recovery.INDEPENDENT_AGENT_BOOTSTRAP + '/resources.yaml')).read_bytes()
    archive, manifest = compile_bundle(previous, rendered)
    bundle = tmp_path / 'release.bundle'
    bundle.write_bytes(archive)
    repo = tmp_path / 'source'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    source = repo / ('contracts/' + recovery.INDEPENDENT_AGENT_BOOTSTRAP + '.yaml')
    source.parent.mkdir()
    source.write_text(yaml.safe_dump(previous))
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '-qm', 'public old contract fixture'], cwd=repo, check=True)
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    state = {'schemaVersion': 'delivery.re8ch.com/accepted-state/v1alpha1',
             'releaseId': recovery.INDEPENDENT_AGENT_BOOTSTRAP,
             'lastOperationId': str(uuid.uuid4()), 'requestDigest': 'sha256:' + 'a' * 64,
             'bundleReference': 'oci://ghcr.io/pillars-infra/network-gitops-release/' + recovery.INDEPENDENT_AGENT_BOOTSTRAP,
             'payloadDigest': digest(archive), 'appliedDigest': 'sha256:' + 'b' * 64,
             'inventoryDigest': manifest['inventoryDigest'], 'inventory': manifest['inventory'],
             'objectRefs': [], 'sequence': 7, 'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
             'blocked': True, 'blockedReason': 'preserve existing failure'}
    cm = {'metadata': {'name': materialize.state_configmap_name(state['releaseId']),
                        'namespace': 'among-clusters', 'uid': str(uuid.uuid4()), 'resourceVersion': '123'},
          'data': {'accepted-state.json': json.dumps(state)}}
    signatures = [{'critical': {'image': {'docker-manifest-digest': state['appliedDigest']},
                                'identity': {'docker-reference': state['bundleReference'].removeprefix('oci://')}},
                   'optional': {'githubWorkflowSha': sha, 'githubWorkflowRepository': 'pillars-infra/network-gitops'}}]
    return cm, contract, signatures, bundle, repo


def test_signed_source_proves_legacy_target_without_reset_or_cluster_write(tmp_path):
    cm, contract, signatures, bundle, repo = fixture(tmp_path)
    before = json.loads(cm['data']['accepted-state.json'])
    with pytest.raises(ValueError, match='another cluster target'):
        materialize.assert_state_target(before, contract)
    evidence = recovery.adopt(cm, contract, signatures, bundle, repo)
    after = json.loads(cm['data']['accepted-state.json'])
    assert evidence['adopted'] and after.pop('clusterRef') == 're8ch-atlantic'
    assert after == before  # blocked flag, sequence, digests and failure remain intact
    assert cm['metadata']['resourceVersion'] == '123'
    materialize.assert_state_target(json.loads(cm['data']['accepted-state.json']), contract)


@pytest.mark.parametrize('change', ['explicit-main', 'binding', 'wrong-oci', 'wrong-signature',
                                    'wrong-repository', 'wrong-object', 'payload-tamper'])
def test_state_adoption_rejects_unproven_or_conflicting_identity(tmp_path, change):
    cm, contract, signatures, bundle, repo = fixture(tmp_path)
    state = json.loads(cm['data']['accepted-state.json'])
    if change == 'explicit-main': state['clusterRef'] = 're8ch'
    elif change == 'binding': state['clusterBindingDigest'] = 'c' * 64
    elif change == 'wrong-oci': state['bundleReference'] = 'oci://unreviewed.invalid/other'
    elif change == 'wrong-signature': signatures[0]['critical']['image']['docker-manifest-digest'] = 'sha256:' + 'd' * 64
    elif change == 'wrong-repository': signatures[0]['optional']['githubWorkflowRepository'] = 'other/repository'
    elif change == 'wrong-object': cm['metadata']['namespace'] = 'default'
    else: state['payloadDigest'] = 'sha256:' + 'e' * 64
    cm['data']['accepted-state.json'] = json.dumps(state)
    with pytest.raises(ValueError): recovery.adopt(cm, contract, signatures, bundle, repo)


def test_validly_signed_bundle_for_main_never_adopts_as_atlantic(tmp_path):
    cm, contract, signatures, bundle, repo = fixture(tmp_path, 're8ch')
    with pytest.raises(ValueError, match='does not prove this cluster target'):
        recovery.adopt(cm, contract, signatures, bundle, repo)
