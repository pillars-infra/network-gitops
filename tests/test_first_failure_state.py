import itertools
import json
import subprocess
import sys
import uuid
import yaml
import pytest
from test_ssa_release_executor import prepare, executor, materialize, NOW, Runner, staged_release, operation_for


def test_first_health_timeout_persists_failed_result_without_acceptance(tmp_path,monkeypatch):
    value,op,bundle=prepare(tmp_path)
    runner=Runner(live={'metadata':{'generation':2},'spec':{'replicas':1},'status':{'observedGeneration':2,'availableReplicas':0}})
    ticks=itertools.count(0,2);monkeypatch.setattr(executor.time,'monotonic',lambda:next(ticks))
    engine=executor.Executor(runner=runner,now=lambda:NOW,sleeper=lambda _:None)
    root=tmp_path/'root';result=engine.reconcile(value,op,bundle,root,False)
    assert result['outcome']=='failed' and result['health']['status']=='unhealthy'
    assert result['application']=={'status':'complete','attemptedInventory':['apps/Deployment/demo/demo'],'appliedInventory':['apps/Deployment/demo/demo']}
    assert result['observedDigest']==op['bundle']['digest']
    assert not (root/'state/demo.json').exists()
    cm=tmp_path/'cm.json';cm.write_text(json.dumps({'metadata':{'name':'ssa-state-demo','namespace':'demo','resourceVersion':'7'},'data':{}}))
    result_path=tmp_path/'result.json';result_path.write_text(json.dumps(result));patch=tmp_path/'patch.json'
    materialize.state_patch(cm,root,'demo',result_path,patch)
    payload=json.loads(patch.read_text());assert payload['metadata']=={'resourceVersion':'7'}
    assert set(payload['data'])=={'last-result.json'}
    cm.write_text(json.dumps({'metadata':{'name':'ssa-state-demo','namespace':'demo','resourceVersion':'8'},'data':payload['data']}))
    hydrated=tmp_path/'hydrated';materialize.hydrate(cm,hydrated,'demo')
    count=len(runner.calls)
    assert engine.reconcile(value,op,bundle,hydrated,False)==result
    assert len(runner.calls)==count
    # A new approved operation can retry; the failed result is not an accepted baseline.
    retry={**op,'operationId':str(uuid.uuid4()),'idempotencyKey':uuid.uuid4().hex,'nonce':uuid.uuid4().hex}
    runner.live=None
    assert engine.reconcile(value,retry,bundle,hydrated,False)['outcome']=='healthy'
    assert json.loads((hydrated/'state/demo.json').read_text())['sequence']==1


def test_partial_api_failure_records_acknowledged_and_uncertain_writes(tmp_path):
    value,archive,manifest,bundle=staged_release(tmp_path,'partial','v1','x')
    op=operation_for(value,archive,manifest,1)
    base=Runner()
    def runner(argv,**kwargs):
        if argv[:2]==['kubectl','apply'] and '--dry-run=server' not in argv and json.loads(kwargs['input'])['kind']=='ConfigMap':
            return subprocess.CompletedProcess(argv,1,'','request timed out; write outcome unknown')
        return base(argv,**kwargs)
    root=tmp_path/'root';result=executor.Executor(runner=runner,now=lambda:NOW).reconcile(value,op,bundle,root,False)
    assert result['outcome']=='failed' and result['observedDigest'] is None
    assert result['application']['status']=='partial-or-unknown'
    assert result['application']['appliedInventory']==['apps/Deployment/demo/demo']
    assert result['application']['attemptedInventory']==manifest['inventory']
    assert not (root/'state/demo.json').exists()


def test_cli_prints_failure_result_and_returns_nonzero(tmp_path,monkeypatch,capsys):
    value,op,bundle=prepare(tmp_path)
    contract=tmp_path/'contract.yaml';contract.write_text(yaml.safe_dump(value))
    operation=tmp_path/'operation.json';operation.write_text(json.dumps(op))
    monkeypatch.setattr(sys,'argv',['ssa_executor.py','--contract',str(contract),'--operation',str(operation),'--bundle',str(bundle),'--state-dir',str(tmp_path/'root')])
    monkeypatch.setattr(executor.Executor,'reconcile',lambda *args,**kwargs:{'outcome':'failed'})
    assert executor.main()==1
    assert json.loads(capsys.readouterr().out)['outcome']=='failed'


@pytest.mark.parametrize('phase',['apply','health'])
def test_subprocess_timeout_is_durable_and_never_exposes_argv(tmp_path,phase):
    value,op,bundle=prepare(tmp_path)
    base=Runner()
    def runner(argv,**kwargs):
        if (phase=='apply' and argv[:2]==['kubectl','apply'] and '--dry-run=server' not in argv) or (phase=='health' and argv[:2]==['kubectl','get']):
            raise subprocess.TimeoutExpired(['kubectl','--token=fixture-secret'],120,output='sensitive output',stderr='sensitive stderr')
        return base(argv,**kwargs)
    root=tmp_path/'root'
    result=executor.Executor(runner=runner,now=lambda:NOW).reconcile(value,op,bundle,root,False)
    assert result['outcome']=='failed' and result['health']['status']=='unknown'
    assert result['observedDigest'] is None and result['application']['status']=='partial-or-unknown'
    assert result['application']['attemptedInventory']==['apps/Deployment/demo/demo']
    assert result['application']['appliedInventory']==([] if phase=='apply' else ['apps/Deployment/demo/demo'])
    assert not (root/'state/demo.json').exists()
    stored=(root/'results/demo'/f"{op['operationId']}.json").read_text()
    assert 'fixture-secret' not in stored and 'sensitive' not in stored and '--token' not in stored
