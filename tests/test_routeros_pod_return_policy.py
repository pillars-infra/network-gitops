import copy
import json
from pathlib import Path
import types
import sys
from urllib.parse import urlsplit

import pytest
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"operations/releases"))
from compile_native import resolve_routeros_pool_policy


def documents():
    root = list(yaml.safe_load_all((ROOT/'clusters/re8ch/routeros-public-forward-controller.yaml').read_text()))
    return root + list(yaml.safe_load_all((ROOT/'clusters/re8ch/multi-pool/pools.yaml').read_text()))


def context():
    docs = resolve_routeros_pool_policy(documents())
    cm = next(d for d in docs if d and d['kind'] == 'ConfigMap')
    module = types.ModuleType('policy')
    exec(compile(cm['data']['pod_return_policy.py'], 'pod_return_policy.py', 'exec'), module.__dict__)
    return module, json.loads(cm['data']['desired.json'])['podReturnPolicy']


class Router:
    def __init__(self):
        self.calls = []
        self.counter = 100
        self.data = {
            '/routing/bgp/connection': [dict(name='re8ch-r640-podcidr', **{'remote.address':'192.168.88.251/32','remote.as':'4200000128','local.address':'192.168.88.1','input.filter':'re8ch-v2-r640-in','routing-table':'re8ch-service-fast','disabled':'false'})],
            '/routing/table': [{'name':'main','fib':'true'},{'name':'re8ch-service-fast','fib':''}],
            '/routing/filter/rule': [
                {'.id':'*1','chain':'re8ch-v2-r640-in','rule':'if (dst==10.42.6.0/24) { accept }','comment':'legacy'},
                {'.id':'*2','chain':'re8ch-v2-r640-in','rule':'if (dst==10.251.0.4/32) { accept }','comment':'VIP'},
                {'.id':'*3','chain':'re8ch-v2-r640-in','rule':'reject','comment':'guard'},
            ],
            '/routing/rule': [
                {'.id':'*4','dst-address':'10.42.0.0/16','action':'lookup','table':'re8ch-service-fast','comment':'legacy'},
                {'.id':'*5','dst-address':'10.251.0.0/24','action':'lookup','table':'re8ch-service-fast','comment':'VIP'},
                {'.id':'*6','action':'lookup','table':'main','comment':'catchall'},
            ],
            '/routing/bgp/session': [{'.id':'*2800001','remote.address':'192.168.88.251','remote.as':'4200000128','local.address':'192.168.88.1','established':'true','remote.capabilities':'mp,rr,as4'}],
        }

    def request(self, raw, method='GET', body=None):
        self.calls.append((raw,method,copy.deepcopy(body)))
        path = urlsplit(raw).path
        if method == 'GET':
            assert '.proplist=' in raw
            return copy.deepcopy(self.data[path])
        if path == '/routing/bgp/session/refresh':
            assert method == 'POST' and body == {'numbers':'*2800001','address-family':'ip'}
            return {}
        if path.endswith('/move'):
            assert method == 'POST'
            rows = self.data[path[:-5]]
            row = next(x for x in rows if x['.id'] == body['numbers'])
            rows.remove(row)
            anchor = next(x for x in rows if x['.id'] == body['destination'])
            rows.insert(rows.index(anchor),row)
            return {}
        if method == 'PUT':
            self.counter += 1
            row = {'.id':'*'+str(self.counter),**body}
            self.data[path].append(row)
            return copy.deepcopy(row)
        base, identity = path.rsplit('/',1)
        row = next(x for x in self.data[base] if x['.id'] == identity)
        if method == 'PATCH':
            row.update(body)
        else:
            assert method == 'DELETE'
            self.data[base].remove(row)
        return {}

    @property
    def writes(self):
        return [call for call in self.calls if call[1] != 'GET']


def test_projection_uses_authoritative_pool_objects_not_current_node_allocations():
    m,p = context()
    assert set(m.validate_policy(p)) == {'10.64.0.0/14','10.68.0.0/14','10.72.0.0/15','10.74.0.0/15'}
    assert '10.68.9.0/24' not in json.dumps(p) and '10.68.22.0/24' not in json.dumps(p)
    source = documents()
    next(x for x in source if x and x['kind']=='CiliumPodIPPool' and x['metadata']['name']=='tenant-apps')['spec']['ipv4']['cidrs'] = ['10.68.0.0/15']
    projected = resolve_routeros_pool_policy(source)
    policy = json.loads(next(x for x in projected if x and x['kind']=='ConfigMap')['data']['desired.json'])['podReturnPolicy']
    assert '10.68.0.0/15' in m.validate_policy(policy)
    assert '10.68.0.0/14' not in m.validate_policy(policy)


@pytest.mark.parametrize('fault',['missing','mask','outside','overlap'])
def test_projection_rejects_unknown_or_invalid_authority(fault):
    source = documents()
    pool = next(x for x in source if x and x['kind']=='CiliumPodIPPool' and x['metadata']['name']=='tenant-apps')
    if fault=='missing': source.remove(pool)
    elif fault=='mask': pool['spec']['ipv4']['maskSize']=25
    elif fault=='outside': pool['spec']['ipv4']['cidrs']=['0.0.0.0/0']
    else: pool['spec']['ipv4']['cidrs']=['10.64.0.0/14']
    with pytest.raises(ValueError): resolve_routeros_pool_policy(source)


def test_real_plan_and_convergence_preserve_peer_vip_default_and_rule_priority():
    m,p=context();r=Router();before=copy.deepcopy(r.data)
    plan=m.plan_pod_return(r,p)
    assert r.writes==[] and len(plan['actions'])==8 and plan['refresh']=='*2800001'
    m.apply_pod_return(r,plan)
    imports=r.data['/routing/filter/rule'];lookups=r.data['/routing/rule']
    assert all(imports.index(x)<imports.index(next(x for x in imports if x['.id']=='*3')) for x in imports if x.get('comment','').startswith(m.OWNER))
    assert all(lookups.index(x)<lookups.index(next(x for x in lookups if x['.id']=='*4')) for x in lookups if x.get('comment','').startswith(m.OWNER))
    for path in ['/routing/bgp/connection','/routing/table','/routing/bgp/session']:
        assert r.data[path]==before[path]
    assert all(x in imports for x in before['/routing/filter/rule'])
    assert all(x in lookups for x in before['/routing/rule'])
    assert all(x.get('action')=='lookup' for x in lookups if x.get('comment','').startswith(m.OWNER))
    assert len([x for x in r.writes if x[0].endswith('/refresh')])==1
    r.calls=[]
    second=m.plan_pod_return(r,p);m.apply_pod_return(r,second)
    assert second=={'actions':[],'refresh':None} and r.writes==[]


@pytest.mark.parametrize('fault',['wrong-as','shared-peer','missing-reject','missing-routing-anchor','bad-session','no-refresh-capability','foreign-owner'])
def test_unknown_runtime_scope_has_zero_writes(fault):
    m,p=context();r=Router()
    if fault=='wrong-as': r.data['/routing/bgp/connection'][0]['remote.as']='65000'
    elif fault=='shared-peer': r.data['/routing/bgp/connection'].append(r.data['/routing/bgp/connection'][0]|{'remote.address':'192.0.2.1'})
    elif fault=='missing-reject': r.data['/routing/filter/rule'].pop()
    elif fault=='missing-routing-anchor': r.data['/routing/rule'].pop(0)
    elif fault=='bad-session': r.data['/routing/bgp/session'][0]['established']='false'
    elif fault=='no-refresh-capability': r.data['/routing/bgp/session'][0]['remote.capabilities']='mp'
    else: r.data['/routing/filter/rule'].append({'.id':'*foreign','chain':'foreign','comment':m.OWNER+' import other'})
    with pytest.raises(ValueError): m.plan_pod_return(r,p)
    assert r.writes==[]


def test_removed_policy_family_deletes_only_exact_owned_rows_and_soft_refreshes():
    m,p=context();r=Router();m.apply_pod_return(r,m.plan_pod_return(r,p));baseline=copy.deepcopy(r.data)
    p['poolRefs'].remove('jobs-sandbox');p['approvedPools']=[x for x in p['approvedPools'] if x['poolRef']!='jobs-sandbox']
    r.calls=[];plan=m.plan_pod_return(r,p);assert len(plan['actions'])==2
    assert all(x[0]=='delete' for x in plan['actions'])
    m.apply_pod_return(r,plan)
    assert all('10.72.0.0/15' not in x.get('comment','') for path in ['/routing/rule','/routing/filter/rule'] for x in r.data[path])
    assert next(x for x in r.data['/routing/filter/rule'] if x['.id']=='*2') in baseline['/routing/filter/rule']
    assert len([x for x in r.writes if x[0].endswith('/refresh')])==1


def test_existing_owned_rule_below_catchall_is_moved_without_peer_reset():
    m,p=context();r=Router();m.apply_pod_return(r,m.plan_pod_return(r,p))
    row=next(x for x in r.data['/routing/rule'] if x.get('comment','').startswith(m.OWNER))
    r.data['/routing/rule'].remove(row);r.data['/routing/rule'].append(row);r.calls=[]
    plan=m.plan_pod_return(r,p);assert len(plan['actions'])==1 and plan['actions'][0][0]=='move'
    m.apply_pod_return(r,plan)
    assert not any('/routing/bgp/connection' in x[0] or x[0].endswith('/reset') for x in r.writes)


def test_static_root_has_the_same_derived_pools_as_native_projection():
    original = next(d for d in documents() if d and d['kind']=='ConfigMap')
    projected = next(d for d in resolve_routeros_pool_policy(documents()) if d and d['kind']=='ConfigMap')
    assert original['data']['desired.json'] == projected['data']['desired.json']


def test_exact_session_identifier_cannot_expand_refresh_to_other_peers():
    m,p=context();r=Router();r.data['/routing/bgp/session'][0]['.id']='*1,*2'
    with pytest.raises(ValueError,match='exact RouterOS object identity'):
        m.plan_pod_return(r,p)
    assert r.writes==[]


def test_ops_delivery_has_configuration_before_startup_only_module():
    contract=yaml.safe_load((ROOT/'contracts/networking-native-ops.yaml').read_text())
    assert contract['spec']['lifecycle']['stages'][0]=={'name':'configuration','kinds':['ConfigMap']}
    assert 'Deployment' in contract['spec']['lifecycle']['stages'][1]['kinds']
    import hashlib
    docs=documents();cm=next(d for d in docs if d and d['kind']=='ConfigMap');deploy=next(d for d in docs if d and d['kind']=='Deployment')
    want=hashlib.sha256((cm['data']['reconcile.py']+cm['data']['pod_return_policy.py']).encode()).hexdigest()
    assert deploy['spec']['template']['metadata']['annotations']['networking.re8ch.com/return-policy-code-sha256']==want


def test_failed_refresh_remains_pending_without_replaying_configuration():
    m,p=context();r=Router();request=r.request
    def fail_refresh(path,method='GET',body=None):
        if path.endswith('/refresh'):
            raise TimeoutError('diagnostic fixture')
        return request(path,method,body)
    r.request=fail_refresh
    with pytest.raises(TimeoutError):
        m.apply_pod_return(r,m.plan_pod_return(r,p))
    r.request=request;r.calls=[]
    plan=m.plan_pod_return(r,p)
    assert plan=={'actions':[],'refresh':'*2800001'}
    m.apply_pod_return(r,plan)
    assert len(r.writes)==1 and r.writes[0][0].endswith('/refresh')
    r.calls=[];m.apply_pod_return(r,m.plan_pod_return(r,p))
    assert r.writes==[]


def test_restart_refreshes_existing_owned_policy_once_with_fresh_session_validation():
    m,p=context();r=Router();m.apply_pod_return(r,m.plan_pod_return(r,p));r.calls=[]
    restarted,_=context()
    r.data['/routing/bgp/session'][0]['established']='false'
    with pytest.raises(ValueError,match='fresh exact'):
        restarted.plan_pod_return(r,p)
    assert r.writes==[]
    r.data['/routing/bgp/session'][0]['established']='true'
    plan=restarted.plan_pod_return(r,p)
    assert plan=={'actions':[],'refresh':'*2800001'}
    restarted.apply_pod_return(r,plan);assert len(r.writes)==1
    r.calls=[];restarted.apply_pod_return(r,restarted.plan_pod_return(r,p))
    assert r.writes==[]
