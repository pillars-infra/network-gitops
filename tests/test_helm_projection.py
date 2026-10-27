import copy
import json
from pathlib import Path
import pytest
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"operations/releases"))
import yaml
from compile_helm import normalize, fetch_chart, render
from profile import validate_contract
ROOT=Path(__file__).resolve().parents[1]

def test_normalization_preserves_cluster_scope_and_supplies_chart_namespace():
    docs=[{'apiVersion':'v1','kind':'Service','metadata':{'name':'service','annotations':None}}, {'apiVersion':'gateway.networking.k8s.io/v1','kind':'GatewayClass','metadata':{'name':'gateway'}}, {'apiVersion':'apiextensions.k8s.io/v1','kind':'CustomResourceDefinition','metadata':{'name':'things.example.com'},'spec':{'names':{'kind':'Thing'},'scope':'Cluster'}}, {'apiVersion':'example.com/v1','kind':'Thing','metadata':{'name':'thing'}}]
    result=normalize(docs,'target')
    assert result[0]['metadata']=={'name':'service','namespace':'target'}
    assert all('namespace' not in x['metadata'] for x in result[1:])

def test_chart_cache_cannot_override_digest(tmp_path):
    expected='a'*64
    (tmp_path/f'chart-{expected}.tgz').write_bytes(b'wrong chart')
    with pytest.raises(ValueError,match='cached chart digest'):
        fetch_chart('chart',{'chart':{'oci':'oci://ghcr.io/example/chart@sha256:'+'b'*64,'sha256':expected}},tmp_path)

@pytest.mark.parametrize('extra',[{'sops':{'mac':'encrypted'}},{'spec':{'valuesFrom':[{'kind':'Secret','name':'restricted'}]}}])
def test_plain_renderer_refuses_restricted_inputs(extra):
    release={'metadata':{'name':'test'},'spec':{'targetNamespace':'test'}}
    if 'spec' in extra:release['spec'].update(extra['spec'])
    else:release.update(extra)
    with pytest.raises(ValueError,match='protected resolution'):
        render(release,Path('unused-chart.tgz'),'v1.36.0-rc3+k3s1')

def test_public_helm_cohort_has_no_secret_rbac_or_hooks():
    ledger=json.loads((ROOT/'operations/releases/helm-authority.json').read_text())
    assert len(ledger['charts'])==4
    assert len(ledger['releases'])==6
    for release in ledger['releases']:
        validate_contract(Path(release['contract']))
        docs=list(yaml.safe_load_all((ROOT/release['source']['path']/'resources.yaml').read_text()))
        assert all(d['kind'] not in {'Secret','Role','RoleBinding','ClusterRole','ClusterRoleBinding'} for d in docs)
        assert all('helm.sh/hook' not in d['metadata'].get('annotations',{}) for d in docs)
    assert len([x for x in ledger['omitted'] if x['reason']=='preserve-existing-secret'])==3
    assert any(x['identity'].endswith('/advanced-fabric') and x['reason']=='protected-render-required' for x in ledger['omitted'])

def test_public_edge_post_renderer_and_cloud_dns_placement_are_retained():
    docs=list(yaml.safe_load_all((ROOT/'releases/networking-helm-public-edge-manager-regional-routing/resources.yaml').read_text()))
    d=next(x for x in docs if x['kind']=='Deployment' and x['metadata']['name']=='public-edge-manager-controller')
    spec=d['spec']['template']['spec']
    assert spec['hostNetwork'] is True
    terms=spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
    assert any(e['key']=='scheduling.re8ch.com/provider' and e['operator']=='Exists' for t in terms for e in t['matchExpressions'])
    assert spec['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution']
