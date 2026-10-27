#!/usr/bin/env python3
"""Fixed Advanced Fabric protected compiler. Emits ciphertext only."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import yaml
from compile_helm import ROOT, fetch_chart, render
from restricted_configmap import bind_source, decrypt_configmap
from restricted_object import seal
from unified_bundle import object_identity, compile_bundle
NAME='networking-helm-advanced-fabric-kube-system'
STAGE='source-validation'
RECIPIENT='age1c7camhc8ql85t5u4hrjmsmkurfa0n0v7lg05espasa9fqapjz5vqql8lfj'

def command(argv,source=None,**kwargs):
    result=subprocess.run(argv,input=source,text=True,capture_output=True,timeout=120)
    if result.returncode:raise ValueError('protected compiler command failed; diagnostics withheld')
    return result

def merge(base,overlay):
    result=copy.deepcopy(base)
    for key,value in overlay.items():
        result[key]=merge(result.get(key,{}) if isinstance(result.get(key,{}),dict) else {},value) if isinstance(value,dict) else copy.deepcopy(value)
    return result

def hydrate(current,plain):
    if isinstance(current,str) and current.startswith('ENC[AES256_GCM,'):return plain
    if isinstance(current,dict):return {key:hydrate(value,plain.get(key)) for key,value in current.items()}
    if isinstance(current,list):return [hydrate(value,plain[index]) for index,value in enumerate(current)]
    return current

def compile_fixed():
    global STAGE
    if not os.environ.get('SOPS_AGE_KEY'):raise ValueError('protected compiler identity is not provisioned')
    source=[d for d in yaml.safe_load_all((ROOT/'clusters/re8ch/resources.yaml').read_text()) if d]
    original=next(d for d in source if d.get('kind')=='HelmRelease' and d['metadata']['name']=='advanced-fabric')
    inventory=next(d for d in source if d.get('kind')=='ConfigMap' and d['metadata']['name']=='cluster-node-inventory')
    STAGE='values-decryption'
    original_plain=json.loads(command(['sops','--decrypt','--input-type','json','--output-type','json','/dev/stdin'],json.dumps(original)).stdout)
    plain_inventory=decrypt_configmap(bind_source(inventory),command)
    root=command(['kubectl','kustomize','clusters/re8ch']).stdout
    release=next(d for d in yaml.safe_load_all(root) if d and d.get('kind')=='HelmRelease' and d['metadata']['name']=='advanced-fabric')
    # Only reviewed Kustomize overlays are retained; encrypted leaves come from MAC-verified source.
    release['spec']['values']=hydrate(release['spec']['values'],original_plain['spec']['values'])
    expected=[{'kind':'ConfigMap','name':'cluster-node-inventory','valuesKey':'advanced-fabric-values.yaml'}]
    if release['spec'].pop('valuesFrom')!=expected:raise ValueError('unreviewed values dependency')
    release.pop('sops')
    release['spec']['values']=merge(yaml.safe_load(plain_inventory['data']['advanced-fabric-values.yaml']),release['spec']['values'])
    STAGE='chart-validation'
    locks=json.loads((ROOT/'operations/releases/helm-lock.json').read_text())
    if command(['helm','version','--short']).stdout.strip().split('+')[0]!=locks['helmVersion']:raise ValueError('Helm compiler version differs')
    locked=locks['releases']['advanced-fabric']
    if release['spec']['releaseName']!=locked['releaseName'] or release['spec']['targetNamespace']!=locked['namespace']:raise ValueError('release identity differs')
    reference=release['spec']['chartRef']
    if reference.get('kind')!='OCIRepository' or reference.get('namespace',release['metadata']['namespace'])!=release['metadata']['namespace']:raise ValueError('unreviewed chart reference')
    declared=next(d for d in yaml.safe_load_all(root) if d and d.get('kind')=='OCIRepository' and d['metadata']['name']==reference['name'] and d['metadata']['namespace']==release['metadata']['namespace'])
    if locked['chart']['oci']!=declared['spec']['url']+'@'+declared['spec']['ref']['digest']:raise ValueError('Helm OCI declaration differs from lock')
    chart=fetch_chart('advanced-fabric',locked,ROOT/'.cache/network-charts')
    STAGE='chart-render'
    objects=render(release,chart,locks['kubernetesVersion'])
    STAGE='inventory-validation'
    observed=json.loads((ROOT/'operations/releases/advanced-fabric-inventory.json').read_text())['objects']
    selected={object_identity({'apiVersion':o['apiVersion'],'kind':o['kind'],'metadata':{'name':o['name'],**({'namespace':o['namespace']} if o['namespace'] else {})}}) for o in observed if o['kind'] not in {'Role','RoleBinding','ClusterRole','ClusterRoleBinding'}}
    rendered={object_identity(o):o for o in objects if o['kind'] not in {'Role','RoleBinding','ClusterRole','ClusterRoleBinding','CustomResourceDefinition'}}
    if set(rendered)!=selected:raise ValueError('render inventory differs from reviewed live adoption set')
    STAGE='output-encryption'
    encrypted=[seal(rendered[key],RECIPIENT,command) for key in sorted(selected)]
    output=yaml.safe_dump_all(encrypted,sort_keys=False)
    contract=yaml.safe_load((ROOT/f'contracts/{NAME}.yaml').read_text())
    STAGE='bundle-validation'
    compile_bundle(contract,output.encode())
    return output

if __name__=='__main__':
    try:
        output=compile_fixed()
        target=Path(os.environ['RUNNER_TEMP'])/'protected-rendered.yaml'
        target.write_text(output);target.chmod(0o600)
        print('Protected Advanced Fabric ciphertext render complete')
    except Exception:
        raise SystemExit('Protected Advanced Fabric compilation failed at '+STAGE+'; diagnostics withheld') from None
