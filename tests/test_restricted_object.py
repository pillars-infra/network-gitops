import copy
import json
import shutil
import subprocess
import pytest
from restricted_object import seal,decrypt,FIELD
from restricted_configmap import RestrictedConfigError
from unified_bundle import compile_bundle
from compile_protected_helm import merge,hydrate

@pytest.fixture
def crypto(tmp_path,monkeypatch):
    if not shutil.which('sops') or not shutil.which('age-keygen'):pytest.skip('real crypto tools required')
    key=tmp_path/'key';subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)],text=True).strip()
    monkeypatch.delenv('SOPS_AGE_KEY',raising=False);monkeypatch.setenv('SOPS_AGE_KEY_FILE',str(key))
    def run(argv,source,**kwargs):return subprocess.run(argv,input=source,text=True,capture_output=True,check=True)
    yield recipient,run
    key.unlink()

def test_real_cluster_spec_ciphertext_roundtrip_and_substitution(crypto):
    recipient,run=crypto
    obj={'apiVersion':'networking.advfab.org/v1alpha1','kind':'AdvancedFabric','metadata':{'name':'advanced-fabric'},'spec':{'restricted':'private-fixture-only'}}
    sealed=seal(obj,recipient,run)
    assert 'private-fixture-only' not in json.dumps(sealed)
    assert decrypt(json.loads(json.dumps(sealed,sort_keys=True)),run)==obj
    tampered=copy.deepcopy(sealed);tampered['metadata']['name']='other'
    with pytest.raises(RestrictedConfigError):decrypt(tampered,run)
    sealed['kind']='Secret'
    with pytest.raises(RestrictedConfigError):decrypt(sealed,run)

def test_protected_values_merge_preserves_reviewed_overlay():
    assert merge({'x':{'a':1,'b':2}},{'x':{'a':3}})=={'x':{'a':3,'b':2}}
    assert hydrate({'secret':'ENC[AES256_GCM,x]','public':'reviewed'}, {'secret':'decoded','public':'old'})=={'secret':'decoded','public':'reviewed'}


def test_protected_compiler_never_forwards_child_diagnostics(monkeypatch):
    from compile_protected_helm import command
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess([],1,'private-spec','private-stderr'))
    with pytest.raises(ValueError) as error:command(['helm'],None)
    assert 'private' not in str(error.value)


def test_protected_overlay_preserves_new_list_entries_and_nested_maps():
    current={'secret':'ENC[AES256_GCM,fixture]','tolerations':[{'key':'old'},{'key':'new','effect':'NoSchedule'}],'newAffinity':{'terms':[{'key':'provider'}]}}
    original={'secret':'decoded','tolerations':[{'key':'old'}]}
    expected=copy.deepcopy(current);expected['secret']='decoded'
    assert hydrate(current,original)==expected
    with pytest.raises(ValueError,match='no authenticated source'):
        hydrate({'new':'ENC[AES256_GCM,fixture]'},original)


def test_helm_test_hooks_are_never_adopted_into_runtime():
    from compile_protected_helm import runtime_objects
    hook={'apiVersion':'v1','kind':'Pod','metadata':{'name':'test-only','namespace':'kube-system','annotations':{'helm.sh/hook':'test'}}}
    role={'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':{'name':'platform','namespace':'kube-system'}}
    service={'apiVersion':'v1','kind':'Service','metadata':{'name':'runtime','namespace':'kube-system'}}
    assert list(runtime_objects([hook,role,service]))==['core/Service/kube-system/runtime']
