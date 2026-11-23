"""Exercise reviewed post-renderers against the immutable public AF chart."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'operations/releases'))
from compile_helm import fetch_chart, render


def test_effective_af_post_renderers_preserve_stream_collector_capacity_and_window():
    # Private Helm values remain encrypted. Only public synthetic values and the
    # actual reviewed, non-secret post-renderer policy enter this render.
    source = subprocess.check_output(['kubectl','kustomize','clusters/re8ch'], cwd=ROOT, text=True)
    release = next(o for o in yaml.safe_load_all(source) if o and o.get('kind')=='HelmRelease'
                   and o['metadata']['name']=='advanced-fabric')
    public = {'metadata':{'name':'advanced-fabric'}, 'spec':{
        'releaseName':'service-vip-fabric', 'targetNamespace':'kube-system',
        'values':{'advancedFabric':{'enabled':True,'runtimeNamespace':'kube-system',
                                   'networkQuality':{'enabled':True}}},
        'postRenderers':copy.deepcopy(release['spec']['postRenderers'])}}
    locks=json.loads((ROOT/'operations/releases/helm-lock.json').read_text())
    chart=fetch_chart('advanced-fabric',locks['releases']['advanced-fabric'],ROOT/'.cache/charts')
    objects=render(public,chart,locks['kubernetesVersion'])
    agent=next(o for o in objects if o['kind']=='DaemonSet' and o['metadata']['name']=='advanced-fabric-agent')
    containers={c['name']:c for c in agent['spec']['template']['spec']['containers']}
    traffic=containers['service-traffic-window']
    assert next(e['value'] for e in traffic['env'] if e['name']=='SERVICE_TRAFFIC_WINDOW_SECONDS')=='15'
    assert traffic['resources']=={'requests':{'cpu':'100m','memory':'128Mi'},
                                 'limits':{'cpu':'2','memory':'1Gi'}}
    # The previous positional patch accidentally treated this collector as the
    # host agent. Neither collector settings nor namespace identity may drift.
    assert next(e for e in containers['agent']['env'] if e['name']=='POD_NAMESPACE')['valueFrom']['fieldRef']['fieldPath']=='metadata.namespace'
    assert agent['spec']['template']['spec']['affinity']['nodeAffinity']
