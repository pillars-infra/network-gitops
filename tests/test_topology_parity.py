import copy
import hashlib
import json
import subprocess
import pytest
import topology_parity as parity


def obj():return {'apiVersion':parity.API,'kind':'AdvancedFabric','metadata':{'name':'advanced-fabric','uid':'fixture-uid','resourceVersion':'fixture-version'},'spec':{'nodes':[{'name':'fixture','private':'do-not-log'}]}}

def runner(monkeypatch,live=None,source='fixture-source'):
    monkeypatch.setattr(parity,'SOURCE_SHA256',hashlib.sha256(source.encode()).hexdigest())
    calls=[]
    def call(argv,**kwargs):
        assert kwargs['redact'] is True
        calls.append(argv)
        payload={'data':{'bundle.json':source}} if argv[2]=='configmap' else live or obj()
        return subprocess.CompletedProcess(argv,0,json.dumps(payload),'')
    return call,calls

def test_first_adoption_requires_exact_source_and_unchanged_desired_topology(monkeypatch):
    live=obj();live['spec']['serverDefault']=True
    run,calls=runner(monkeypatch,live)
    assert parity.check([obj()],None,run)=={'sourcePinMatches':True,'initialAdoption':True,'differenceCount':0}
    assert len(calls)==2 and all(a[:2]==['kubectl','get'] for a in calls)

@pytest.mark.parametrize('kind',['value','new','list'])
def test_topology_drift_is_redacted_and_blocks_initial_adoption(monkeypatch,kind):
    live=obj()
    if kind=='value':live['spec']['nodes'][0]['private']='different-private'
    if kind=='new':live['spec']={}
    if kind=='list':live['spec']['nodes']=[]
    run,_=runner(monkeypatch,live)
    with pytest.raises(parity.TopologyParityError) as exc:parity.check([obj()],None,run)
    assert 'difference count=' in str(exc.value) and 'private' not in str(exc.value)

def test_wrong_pin_fails_before_live_resource_read(monkeypatch):
    run,calls=runner(monkeypatch);monkeypatch.setattr(parity,'SOURCE_SHA256','0'*64)
    with pytest.raises(parity.TopologyParityError,match='pin mismatch'):parity.check([obj()],None,run)
    assert len(calls)==1

def test_accepted_reconcile_can_repair_drift_but_still_checks_source_pin(monkeypatch):
    run,calls=runner(monkeypatch)
    assert parity.check([obj()],{'healthyDigest':'sha256:accepted'},run)['initialAdoption'] is False
    assert len(calls)==1

def test_complete_accepted_degraded_baseline_allows_reviewed_repairs(monkeypatch):
    run,calls=runner(monkeypatch)
    previous={'acceptedDigest':'sha256:baseline','appliedDigest':'sha256:baseline',
              'inventory':['networking.advfab.org/AdvancedFabric/_/advanced-fabric'], 'blocked':False}
    assert parity.check([obj()],previous,run)['initialAdoption'] is False
    assert len(calls)==1
    assert 'healthyDigest' not in previous  # Never promote degraded to healthy.

@pytest.mark.parametrize('change',[{'acceptedDigest':'sha256:different'}, {'blocked':True}, {'inventory':[]}])
def test_unaccepted_or_blocked_baseline_does_not_skip_topology_parity(monkeypatch,change):
    previous={'acceptedDigest':'sha256:baseline','appliedDigest':'sha256:baseline',
              'inventory':['networking.advfab.org/AdvancedFabric/_/advanced-fabric'], 'blocked':False, **change}
    live=obj();live['spec']['nodes']=[]
    run,_=runner(monkeypatch,live)
    with pytest.raises(parity.TopologyParityError,match='difference count=1'):
        parity.check([obj()],previous,run)

def test_source_read_diagnostics_never_expose_contents():
    def fail(*a,**k):raise ValueError('do-not-log source or credential')
    with pytest.raises(parity.TopologyParityError) as exc:parity.check([obj()],None,fail)
    assert 'do-not-log' not in str(exc.value)


def test_status_only_version_change_binds_the_compared_snapshot(monkeypatch):
    live=obj();live['metadata']['resourceVersion']='concurrent-change'
    live['status']={'observedAt':'new-status'}
    run,_=runner(monkeypatch,live)
    desired=obj()
    assert parity.check([desired],None,run)['differenceCount']==0
    assert desired['metadata']['resourceVersion']=='concurrent-change'

def test_recreated_topology_identity_blocks_adoption(monkeypatch):
    live=obj();live['metadata']['uid']='replacement-uid'
    run,_=runner(monkeypatch,live)
    with pytest.raises(parity.TopologyParityError,match='identity changed'):
        parity.check([obj()],None,run)

def test_concurrent_spec_change_still_blocks_adoption(monkeypatch):
    live=obj();live['metadata']['resourceVersion']='concurrent-change'
    live['spec']['nodes'][0]['private']='changed-private'
    run,_=runner(monkeypatch,live)
    with pytest.raises(parity.TopologyParityError,match='difference count=1'):
        parity.check([obj()],None,run)


def test_parity_diagnostics_classify_without_values_or_paths():
    desired={'virtualIngress':{'tolerations':[{'key':'private-taint'}]},'controller':{'image':'private-image'},'private-topology':{'private-key':'secret-value'}}
    actual={'virtualIngress':{'tolerations':[]},'controller':{'image':'old-image'},'private-topology':{}}
    counts=parity.difference_counts(desired,actual)
    assert counts=={'placement':1,'controllerRuntime':1,'virtualIngressRuntime':0,'networkOrOther':1}
    assert 'private' not in json.dumps(counts) and 'secret' not in json.dumps(counts)
