import copy
import json
from pathlib import Path
import sys
import pytest
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operations/releases'))
from compile_native import classify, project
from profile import validate_contract

def obj(kind='ConfigMap',namespace='demo'):
    return {'apiVersion':'v1','kind':kind,'metadata':{'name':'sample',**({'namespace':namespace} if namespace else {})},'data':{'value':'public'}}

@pytest.mark.parametrize('kind',['Secret','HelmRelease','HelmChart','Role','RoleBinding'])
def test_sensitive_or_controller_inputs_never_become_public_native_bundles(kind):
    _,ledger=project([obj(kind)])
    assert ledger['releases']==[]
    assert len(ledger['omitted'])==1

def test_sops_and_unpinned_workloads_are_explicitly_deferred():
    encrypted=obj();encrypted['sops']={'age':[]}
    deployment=obj('Deployment');deployment['spec']={'template':{'spec':{'containers':[{'name':'app','image':'example:latest'}]}}}
    with pytest.raises(ValueError):project([encrypted])
    _,ledger=project([deployment,obj(namespace=None)])
    assert not ledger['releases']
    assert {x['reason'] for x in ledger['omitted']}=={'image-digest-required','cluster-network-authority'}

def test_namespaces_are_separate_and_adoption_does_not_grant_create_delete():
    one=obj(namespace='one');two=obj(namespace='two')
    files,ledger=project([two,one])
    assert [r['namespace'] for r in ledger['releases']]==['one','two']
    for release in ledger['releases']:
        contract=yaml.safe_load(files[release['contract']])
        assert contract['spec']['lifecycle']['prune'] is False
        assert all(rule['verbs']==['get','patch'] for rule in release['rules'])
        assert all(rule['resourceNames'] for rule in release['rules'])
        assert release['stateConfigMap']['metadata']['namespace']==release['namespace']
    assert files==project([one,two])[0]

def test_every_checked_in_contract_is_canonical_and_profile_bound():
    for p in (ROOT/'contracts').glob('networking-native-*.yaml'):
        result=validate_contract(Path('contracts')/p.name)
        assert result['audience'].endswith('/release-executor-networking')
        with pytest.raises(ValueError):validate_contract(p)


def test_rbac_is_platform_owned_without_executor_inventory():
    role=obj('Role');binding=obj('RoleBinding')
    _,ledger=project([role,binding,obj()])
    assert len(ledger['platformBootstrap'])==2
    assert all('/Role/' not in x and '/RoleBinding/' not in x for release in ledger['releases'] for x in release['inventory'])
