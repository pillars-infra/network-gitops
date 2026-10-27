import copy
import hashlib
import json
from pathlib import Path
import subprocess
import pytest
from test_ssa_release_executor import contract, prepare, executor, NOW, canonical, digest, compile_bundle
from restricted_configmap import decrypt_configmap, RestrictedConfigError, bind_source, SOURCE_FIELD
from ssa_preflight import preflight

VALUE='private-topology-test-value'

@pytest.fixture(autouse=True)
def provision_test_identity(monkeypatch):
    monkeypatch.setenv('SOPS_AGE_KEY','test-runner-placeholder-not-a-key')

def envelope():
    return bind_source({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'demo','namespace':'demo','annotations':{'security.re8ch.com/restricted-data-sha256':json.dumps({'nodes.json':hashlib.sha256(VALUE.encode()).hexdigest()})}},'data':{'nodes.json':'ENC[AES256_GCM,data:fixture,type:str]','public':'unchanged'},'sops':{'age':[{'recipient':'age-public-fixture','enc':'encrypted-key'}],'mac':'ENC[AES256_GCM,data:mac,type:str]'}})

def plaintext():
    d=envelope();d.pop(SOURCE_FIELD);d.pop('sops');d['data']['nodes.json']=VALUE;return d

class RestrictedRunner:
    def __init__(self,fail=None):self.calls=[];self.fail=fail
    def __call__(self,argv,**kwargs):
        self.calls.append((argv,kwargs.get('input')))
        if argv[0]=='sops':
            assert 'delivery.re8ch.com/operation-id' not in json.loads(kwargs['input'])['metadata']['annotations']
            if self.fail=='decrypt':return subprocess.CompletedProcess(argv,1,VALUE,VALUE)
            return subprocess.CompletedProcess(argv,0,json.dumps(plaintext()),'')
        if argv[:2]==['cosign','verify'] and self.fail=='signature':return subprocess.CompletedProcess(argv,1,'','invalid signature')
        if argv[:2]==['kubectl','apply']:
            assert VALUE in kwargs['input'] and '"sops"' not in kwargs['input']
            if self.fail=='apply':return subprocess.CompletedProcess(argv,1,VALUE,VALUE)
        return subprocess.CompletedProcess(argv,0,'','')

def request_fixture(tmp_path):
    value,operation,path=prepare(tmp_path)
    identity='core/ConfigMap/demo/demo'
    value['spec']['authorization']['resources']=['core/ConfigMap']
    value['spec']['inventory']['digest']=digest(canonical([identity]))
    archive,manifest=compile_bundle(value,__import__('yaml').safe_dump(envelope()).encode());path.write_bytes(archive)
    operation['contractDigest']=digest(canonical(value));operation['inventoryDigest']=manifest['inventoryDigest']
    operation['bundle'].update(digest=digest(archive),payloadDigest=digest(archive))
    return value,operation,path

def test_signed_ciphertext_is_verified_before_memory_decryption_and_state_stays_redacted(tmp_path):
    value,operation,path=request_fixture(tmp_path);run=RestrictedRunner()
    result=executor.Executor(runner=run,now=lambda:NOW).reconcile(value,operation,path,tmp_path/'state')
    assert result['outcome']=='healthy'
    commands=[c[0][0] for c in run.calls];assert commands.index('cosign')<commands.index('sops')<commands.index('kubectl')
    for p in (tmp_path/'state').rglob('*.json'):assert VALUE not in p.read_text()
    assert VALUE.encode() not in path.read_bytes()

def test_failed_signature_never_decrypts(tmp_path):
    value,operation,path=request_fixture(tmp_path);run=RestrictedRunner('signature')
    with pytest.raises(executor.Rejected):executor.Executor(runner=run,now=lambda:NOW).reconcile(value,operation,path,tmp_path/'state')
    assert not any(c[0][0]=='sops' for c in run.calls)

@pytest.mark.parametrize('failure',['decrypt','apply'])
def test_restricted_command_diagnostics_do_not_escape(tmp_path,failure):
    value,operation,path=request_fixture(tmp_path);run=RestrictedRunner(failure)
    try:result=executor.Executor(runner=run,now=lambda:NOW).reconcile(value,operation,path,tmp_path/'state');observed=json.dumps(result)
    except executor.Rejected as error:observed=str(error)
    assert VALUE not in observed
    assert 'diagnostics withheld' in observed

@pytest.mark.parametrize('mutation',['identity','parity','extra'])
def test_decrypted_identity_and_parity_cannot_change(mutation):
    plain=plaintext()
    if mutation=='identity':plain['metadata']['name']='other'
    if mutation=='parity':plain['data']['nodes.json']='different'
    if mutation=='extra':plain['data']['new']='unexpected'
    with pytest.raises(RestrictedConfigError):decrypt_configmap(envelope(),lambda *a,**kw:subprocess.CompletedProcess([],0,json.dumps(plain),''))

def test_signed_preflight_only_dry_runs_and_never_accepts_state(tmp_path):
    value,operation,path=request_fixture(tmp_path);run=RestrictedRunner()
    result=preflight(executor.Executor(runner=run,now=lambda:NOW),value,operation,path,tmp_path/'state')
    assert result['preflight']=='accepted'
    applies=[argv for argv,_ in run.calls if argv[:2]==['kubectl','apply']]
    assert applies and all('--dry-run=server' in argv for argv in applies)
    assert not list((tmp_path/'state').rglob('*.json'))


def test_missing_provisioned_key_never_uses_runner_local_credentials(tmp_path,monkeypatch):
    monkeypatch.delenv('SOPS_AGE_KEY',raising=False);monkeypatch.delenv('SOPS_AGE_KEY_FILE',raising=False)
    value,operation,path=request_fixture(tmp_path);run=RestrictedRunner()
    with pytest.raises(executor.Rejected,match='not provisioned'):
        executor.Executor(runner=run,now=lambda:NOW).reconcile(value,operation,path,tmp_path/'state')
    assert not any(c[0][0]=='sops' for c in run.calls)

def test_publish_never_receives_age_key_and_runtime_steps_are_protected():
    import yaml
    jobs=yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/static-release.yml').read_text())['jobs']
    assert 'SOPS_AGE_KEY' not in json.dumps(jobs['compile-sign'])
    for name in ['execute','runtime-dry-run']:
        job=jobs[name]
        assert job['environment']=='${{ needs.validate.outputs.environment }}'
        secret_steps=[s for s in job['steps'] if 'SOPS_AGE_KEY' in s.get('env',{})]
        assert len(secret_steps)==1
        assert 'cosign verify' in secret_steps[0]['run']


def test_first_rejected_operation_does_not_overwrite_bootstrap_state(tmp_path):
    import operation_materialize
    cm=tmp_path/'cm.json';cm.write_text(json.dumps({'metadata':{'name':'ssa-state-demo','resourceVersion':'1'},'data':{}}))
    patch=tmp_path/'patch.json';patch.write_text('stale')
    operation_materialize.state_patch(cm,tmp_path/'empty-state','demo',tmp_path/'result.json',patch)
    assert not patch.exists()


def test_real_sops_survives_sorted_artifact_and_rejects_source_tampering(tmp_path,monkeypatch):
    import os
    import shutil
    if not shutil.which('sops') or not shutil.which('age-keygen'):
        pytest.skip('real SOPS roundtrip requires sops and age-keygen')
    key=tmp_path/'ephemeral-age-key'
    subprocess.run(['age-keygen','-o',str(key)],check=True,capture_output=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)],text=True).strip()
    monkeypatch.delenv('SOPS_AGE_KEY',raising=False)
    monkeypatch.setenv('SOPS_AGE_KEY_FILE',str(key))
    plain=plaintext()
    # Deliberately nonalphabetic keys expose traversal-sensitive SOPS MAC order.
    plain={'kind':plain['kind'],'metadata':plain['metadata'],'apiVersion':plain['apiVersion'],'data':plain['data']}
    encrypted=subprocess.run(['sops','--encrypt','--age',recipient,'--encrypted-regex','^(nodes\\.json)$','--input-type','json','--output-type','json','/dev/stdin'],input=json.dumps(plain),text=True,capture_output=True,check=True)
    bound=bind_source(json.loads(encrypted.stdout))
    canonicalized=json.loads(json.dumps(bound,sort_keys=True))
    def run(argv,source,**kwargs):
        return subprocess.run(argv,input=source,text=True,capture_output=True,check=True)
    assert decrypt_configmap(canonicalized,run)==plain
    canonicalized[SOURCE_FIELD]=json.dumps({**json.loads(canonicalized[SOURCE_FIELD]),'kind':'Secret'})
    with pytest.raises(RestrictedConfigError,match='differs'):
        decrypt_configmap(canonicalized,run)
    key.unlink()
