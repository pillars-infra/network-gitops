import copy
import json
from pathlib import Path
import sys
import pytest
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'operations/releases'))
from compile_native import KUBE_API_RELEASE_OBJECTS, classify, project
import profile
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


def test_cluster_inventory_bootstrap_can_recreate_only_its_reviewed_configmap():
    inventory=obj(namespace='flux-network-system')
    inventory['metadata']['name']='cluster-node-inventory'
    files,ledger=project([inventory])
    release=ledger['releases'][0]
    contract=yaml.safe_load(files[release['contract']])

    assert release['releaseId']=='networking-native-flux-network-system'
    assert contract['spec']['authorization']['requireExisting'] is False
    assert contract['spec']['authorization']['objectNames']==['cluster-node-inventory']
    assert {'apiGroups':[''],'resources':['configmaps'],'verbs':['create']} in release['rules']

def test_every_checked_in_contract_is_canonical_and_profile_bound():
    for p in (ROOT/'contracts').glob('networking-native-*.yaml'):
        result=validate_contract(Path('contracts')/p.name)
        assert result['audience'].endswith('/'+result['environment'])
        with pytest.raises(ValueError):validate_contract(p)

def test_atlantic_contract_uses_separate_execution_identity():
    result=validate_contract(Path('contracts/networking-native-atlantic-bootstrap.yaml'))
    assert result['cluster']=='re8ch-atlantic'
    assert result['environment']=='release-executor-networking-atlantic'

def test_unknown_target_cluster_is_rejected(monkeypatch):
    path=ROOT/'contracts/networking-native-atlantic-bootstrap.yaml'
    value=yaml.safe_load(path.read_text())
    value['spec']['target']['cluster']='unknown'
    monkeypatch.setattr(profile.yaml,'safe_load',lambda _: value)
    with pytest.raises(ValueError,match='unsupported networking target cluster'):
        validate_contract(Path('contracts')/path.name)


def test_rbac_is_platform_owned_without_executor_inventory():
    role=obj('Role');binding=obj('RoleBinding')
    _,ledger=project([role,binding,obj()])
    assert len(ledger['platformBootstrap'])==2
    assert all('/Role/' not in x and '/RoleBinding/' not in x for release in ledger['releases'] for x in release['inventory'])


def test_backend_tls_policy_uses_kubernetes_resource_plural():
    policy=obj('BackendTLSPolicy')
    policy['apiVersion']='gateway.networking.k8s.io/v1'
    _,ledger=project([policy])
    rules=ledger['releases'][0]['rules']
    assert any(rule['resources']==['backendtlspolicies'] and rule['resourceNames']==['sample'] for rule in rules)


def test_kube_api_objects_have_a_separate_existing_only_release():
    docs=[]
    for path in (ROOT/'clusters/re8ch/kube-api-observer-proxy.yaml',
                 ROOT/'clusters/re8ch/kube-api-public.yaml'):
        docs.extend(d for d in yaml.safe_load_all(path.read_text()) if d)
    _,ledger=project(docs)
    release=next(x for x in ledger['releases'] if x['releaseId']=='networking-native-kube-api')
    assert set(release['inventory'])==KUBE_API_RELEASE_OBJECTS
    assert release['namespace']=='kube-system'
    assert all(rule['verbs']==['get','patch'] for rule in release['rules'])


def test_atlantic_import_bridge_is_preserved_not_reapplied_or_pruned():
    from compile_native import CONTROLLER_OWNED_RUNTIME_RESULTS
    name='re8ch-atlantic-default-kubernetes-re8ch-atlantic'
    bridge={'apiVersion':'v1','kind':'Service','metadata':{'name':name,'namespace':'byoc-pilot'},
            'spec':{'type':'ExternalName','externalName':next(iter(CONTROLLER_OWNED_RUNTIME_RESULTS.values()))}}
    files,ledger=project([bridge,obj(namespace='byoc-pilot')])
    assert ledger['omitted']==[{'identity':next(iter(CONTROLLER_OWNED_RUNTIME_RESULTS)), 'reason':'controller-owned-runtime-result'}]
    release=ledger['releases'][0]
    assert not any(name in value for value in release['inventory'])
    contract=yaml.safe_load(files[release['contract']])
    assert contract['spec']['lifecycle']['prune'] is False
    assert contract['spec']['lifecycle']['deletionAllowlist']==[]
    assert name not in contract['spec']['authorization']['objectNames']
    changed=copy.deepcopy(bridge);changed['spec']['externalName']='other.example'
    with pytest.raises(ValueError,match='bootstrap source'):project([changed])
