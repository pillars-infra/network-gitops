import json
import subprocess
from pathlib import Path
import pytest
from test_ssa_release_executor import prepare,executor,NOW,Runner,compile_bundle,canonical,digest

class ExistingRunner(Runner):
    def __init__(self,fault=None):super().__init__();self.fault=fault;self.written=False
    def __call__(self,argv,**kwargs):
        if argv[:2]==['cosign','verify'] and self.fault=='signature':
            self.calls.append((argv,kwargs.get('input')))
            return subprocess.CompletedProcess(argv,1,'','invalid signature')
        if argv[:2]==['kubectl','get'] and 'jsonpath={.metadata.resourceVersion}' in argv:
            self.calls.append((argv,kwargs.get('input')))
            return subprocess.CompletedProcess(argv,1 if self.fault=='missing' else 0,'' if self.fault=='missing' else '17','not found' if self.fault=='missing' else '')
        if argv[:2]==['kubectl','apply']:
            self.calls.append((argv,kwargs.get('input')))
            item=json.loads(kwargs['input']);assert item['metadata']['resourceVersion']=='17'
            if '--dry-run=server' not in argv:
                if self.fault in {'deleted-after-get','version-changed'}:
                    return subprocess.CompletedProcess(argv,1,'','resourceVersion precondition failed')
                self.written=True
            return subprocess.CompletedProcess(argv,0,'','')
        return super().__call__(argv,**kwargs)

def fixture(tmp_path):
    value,op,path=prepare(tmp_path)
    value['spec']['authorization']['requireExisting']=True
    rendered='apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: demo, namespace: demo}\nspec:\n  replicas: 1\n  template:\n    spec:\n      containers:\n      - {name: demo, image: "registry.example/demo@sha256:'+('a'*64)+'"}\n'
    archive,manifest=compile_bundle(value,rendered.encode());path.write_bytes(archive)
    op['contractDigest']=digest(canonical(value));op['inventoryDigest']=manifest['inventoryDigest']
    op['bundle'].update(digest=digest(archive),payloadDigest=digest(archive))
    return value,op,path

@pytest.mark.parametrize('fault',['missing','deleted-after-get','version-changed'])
def test_adoption_never_recreates_missing_or_changed_objects(tmp_path,fault):
    value,op,path=fixture(tmp_path);runner=ExistingRunner(fault)
    with pytest.raises(executor.Rejected):executor.Executor(runner=runner,now=lambda:NOW).reconcile(value,op,path,tmp_path/'state')
    assert not runner.written
    assert not (tmp_path/'state/state/demo.json').exists()
    if fault=='missing':assert not any(c[0][:2]==['kubectl','apply'] for c in runner.calls)

def test_resource_version_precondition_is_bound_after_signature(tmp_path):
    value,op,path=fixture(tmp_path);before=path.read_bytes();runner=ExistingRunner()
    result=executor.Executor(runner=runner,now=lambda:NOW).reconcile(value,op,path,tmp_path/'state')
    assert result['outcome']=='healthy' and runner.written
    names=[c[0][0] for c in runner.calls];assert names.index('cosign')<names.index('kubectl')
    assert path.read_bytes()==before
    applies=[json.loads(data) for argv,data in runner.calls if argv[:2]==['kubectl','apply']]
    assert len(applies)==2 and all(o['metadata']['resourceVersion']=='17' for o in applies)

def test_failed_signature_never_reads_existing_resource(tmp_path):
    value,op,path=fixture(tmp_path);runner=ExistingRunner('signature')
    with pytest.raises(executor.Rejected):executor.Executor(runner=runner,now=lambda:NOW).reconcile(value,op,path,tmp_path/'state')
    assert not any(c[0][0]=='kubectl' for c in runner.calls)

def test_normal_release_without_adoption_flag_keeps_existing_behavior(tmp_path):
    value,op,path=prepare(tmp_path);runner=Runner()
    result=executor.Executor(runner=runner,now=lambda:NOW).reconcile(value,op,path,tmp_path/'state',verify_signature=False)
    assert result['outcome']=='healthy'
    assert not any('jsonpath={.metadata.resourceVersion}' in argv for argv,_ in runner.calls)
