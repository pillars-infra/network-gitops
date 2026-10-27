import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from test_ssa_release_executor import prepare, executor, NOW, canonical, digest, compile_bundle, rendered
from profile import replay_matrix, replay_provenance, REPOSITORY, WORKFLOW, ENVIRONMENT, AUDIENCE, SIGNER, REPLAY_AUDIENCE

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('fault',[None,'missing','unhealthy','blocked','digest','reference','inventory','force','rollback','actual-audience'])
def test_replay_requires_exact_healthy_acceptance(tmp_path,monkeypatch,fault):
    c,op,bundle=prepare(tmp_path,sequence=2)
    c['spec']['authorityDomain']='networking'
    c['spec']['provenance'].update(repository=REPOSITORY,workflow=WORKFLOW,environment=ENVIRONMENT,audience=AUDIENCE,signer=SIGNER)
    archive,manifest=compile_bundle(c,rendered());bundle.write_bytes(archive)
    op['contractDigest']=digest(canonical(c))
    op['bundle'].update(reference='oci://ghcr.io/pillars-infra/network-gitops-release/demo',digest=digest(archive),payloadDigest=digest(archive),signer=SIGNER)
    op['github'].update(replay_provenance(c))
    op['previousApprovedDigest']=digest(archive)
    state=dict(releaseId='demo',sequence=1,healthyDigest=digest(archive),appliedDigest=digest(archive),payloadDigest=digest(archive),bundleReference=op['bundle']['reference'],inventoryDigest=op['inventoryDigest'])
    if fault=='missing':state=None;op['sequence']=1
    elif fault=='unhealthy':state['healthyDigest']='sha256:'+'0'*64
    elif fault=='blocked':state['blocked']=True
    elif fault=='digest':op['bundle']['digest']='sha256:'+'0'*64
    elif fault=='reference':op['bundle']['reference']='oci://registry.example/attacker'
    elif fault=='inventory':state['inventoryDigest']='sha256:'+'0'*64
    elif fault=='force':op['forceConflictObjects']=['apps/Deployment/demo/demo']
    elif fault=='rollback':op['action']='rollback'
    elif fault=='actual-audience':monkeypatch.setenv('EXECUTOR_AUDIENCE',AUDIENCE)
    store=SimpleNamespace(result=lambda _:None,state=lambda:state)
    if fault:
        with pytest.raises((executor.Rejected,ValueError)):executor.Executor(now=lambda:NOW).validate(c,op,bundle,store)
    else:assert executor.Executor(now=lambda:NOW).validate(c,op,bundle,store)[0]['releaseId']=='demo'

def test_matrix_and_workflow_have_no_publishing_inputs(monkeypatch):
    monkeypatch.chdir(ROOT)
    matrix=replay_matrix()
    assert len(matrix)==34
    assert all(p['audience']==REPLAY_AUDIENCE for p in matrix)
    text=(ROOT/'.github/workflows/networking-reconcile.yml').read_text()
    workflow=yaml.safe_load(text)
    triggers=workflow.get('on',workflow.get(True))
    assert triggers['workflow_dispatch'] is None
    assert triggers['schedule']
    assert '--replay-only' in text and 'accepted-bundle' in text
    assert 'networking-static-release-${{ matrix.contract }}' in text
    assert 'packages: write' not in text
    assert 'flux push' not in text and 'cosign sign' not in text and 'compile_' not in text
