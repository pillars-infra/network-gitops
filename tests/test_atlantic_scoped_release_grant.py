"""Remote Actions must never inherit the interactive wildcard grant."""
from pathlib import Path
import json
import yaml
ROOT=Path(__file__).parents[1]
PATH=ROOT/'clusters/re8ch/among-clusters-atlantic-release-canary.yaml'

def objects():
    return list(yaml.safe_load_all(PATH.read_text()))

def test_release_grant_is_an_exact_named_namespaced_canary():
    grant=next(o for o in objects() if o['kind']=='ManagedAccessGrant')
    assert grant['metadata']['name']=='re8ch-atlantic-networking-canary'
    assert grant['spec']['scope']=='Namespaced'
    assert grant['spec']['namespaces']==['default']
    assert grant['spec']['rules']==[{'apiGroups':[''],'resources':['configmaps'],
        'resourceNames':['re8ch-cloud-target-canary'],'verbs':['get','patch','update','delete']}]
    assert grant['spec']['advertisementRef']=='re8ch-atlantic-default-kubernetes'
    assert grant['spec']['peerRef']=='re8ch-atlantic'

def test_actions_original_principal_has_no_admin_grant_or_pod_proxy():
    roles={o['metadata']['name']:o for o in objects() if o['kind']=='Role'}
    use=roles['networking-atlantic-canary-grant-use']
    assert use['rules']==[{'apiGroups':['peering.re8ch.com'],'resources':['managedaccessgrants'],
        'resourceNames':['re8ch-atlantic-networking-canary'],'verbs':['get','use']}]
    proxy=roles['networking-cloud-platform-exact-proxy']
    assert proxy['metadata']['namespace']=='ai-operations'
    assert proxy['rules']==[{'apiGroups':[''],'resources':['services/proxy'],
        'resourceNames':['re8ch-cloud-platform:19443'],'verbs':['get','create','update','patch','delete']}]
    cloud=roles['re8ch-cloud-platform-execution-grant-metadata']
    assert cloud['rules'][0]['verbs']==['get']
    for binding in (o for o in objects() if o['kind']=='RoleBinding'):
        subject,=binding['subjects']
        if binding['roleRef']['name']==cloud['metadata']['name']:
            assert subject=={'kind':'ServiceAccount','name':'re8ch-cloud-platform','namespace':'ai-operations'}
        else:
            assert subject=={'kind':'Group','name':'re8ch:release-executor:networking','apiGroup':'rbac.authorization.k8s.io'}
    ledger=json.loads((ROOT/'operations/releases/native-authority.json').read_text())
    for o in objects():
        if o['kind'] in ['Role','RoleBinding']: assert o in ledger['platformBootstrap']

def test_remote_approval_is_separate_and_generation_bound():
    docs=list(yaml.safe_load_all((ROOT/'releases/networking-native-atlantic-among-clusters/resources.yaml').read_text()))
    approval=next(o for o in docs if o.get('metadata',{}).get('name')=='among-clusters-approval-re8ch-atlantic-networking-canary')
    assert approval['metadata']['namespace']=='among-clusters'
    assert approval['data']=={'approved':'true','generation':'1','grantRef':'re8ch-atlantic-networking-canary'}
    old=next(o for o in docs if o.get('metadata',{}).get('name')=='among-clusters-approval-re8ch-atlantic-headlamp-admin')
    assert old['data']['grantRef']=='re8ch-atlantic-headlamp-admin'
