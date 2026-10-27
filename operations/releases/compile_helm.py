#!/usr/bin/env python3
"""Render pinned Helm inputs in the cloud; runtime reuses the compiled SSA artifact.

Retains the source HelmRelease only as a reviewed declaration. Cluster bootstrap
objects and RBAC belong to the platform; generated Secrets and hooks are never
silently adopted. Restricted chart values require the protected rendering path.
"""
import argparse
import hashlib
import json
from urllib.parse import urlsplit
import re
from pathlib import Path
import subprocess
import tempfile
import yaml
from compile_native import project
from unified_bundle import CLUSTER_SCOPED, object_identity
ROOT=Path(__file__).resolve().parents[2]
CLUSTER_KINDS=CLUSTER_SCOPED|{'GatewayClass'}

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def fetch_chart(name,lock,cache):
    chart=lock['chart']
    if 'path' in chart:
        path=(ROOT/chart['path']).resolve()
        if ROOT not in path.parents or sha(path)!=chart['sha256']:raise ValueError('vendored chart digest mismatch')
        return path
    ref=chart['oci']
    parsed=urlsplit(ref)
    if parsed.scheme!='oci' or parsed.netloc!='ghcr.io' or not re.fullmatch(r'/[a-z0-9/_.-]+@sha256:[0-9a-f]{64}',parsed.path) or parsed.query or parsed.fragment:
        raise ValueError('chart must bind a GHCR digest')
    path=cache/f"{name}-{chart['sha256']}.tgz"
    if path.exists():
        if sha(path)!=chart['sha256']:raise ValueError('cached chart digest mismatch')
        return path
    cache.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='network-chart-') as td:
        subprocess.run(['helm','pull',ref,'--destination',td],check=True,capture_output=True)
        charts=list(Path(td).glob('*.tgz'))
        if len(charts)!=1 or sha(charts[0])!=chart['sha256']:raise ValueError('downloaded chart digest mismatch')
        path.write_bytes(charts[0].read_bytes())
    return path

def normalize(documents,namespace):
    scopes={o['spec']['names']['kind']:o['spec']['scope'] for o in documents if o.get('kind')=='CustomResourceDefinition'}
    for o in documents:
        meta=o['metadata']
        for key in ['labels','annotations']:
            if meta.get(key)==None:meta.pop(key,None)
        if o['kind'] not in CLUSTER_KINDS and scopes.get(o['kind'])!='Cluster':meta.setdefault('namespace',namespace)
    return documents

def checked_output(argv):
    result=subprocess.run(argv,capture_output=True)
    if result.returncode:raise ValueError('Helm render command failed; diagnostics withheld')
    return result.stdout

def render(release,chart,version):
    spec=release['spec'];name=spec.get('releaseName',release['metadata']['name']);namespace=spec['targetNamespace']
    if release.get('sops') or spec.get('valuesFrom'):raise ValueError('restricted source requires protected resolution')
    with tempfile.TemporaryDirectory(prefix='network-helm-render-') as td:
        td=Path(td);values=td/'values.yaml';values.write_text(yaml.safe_dump(spec.get('values',{})));values.chmod(0o600)
        output=checked_output(['helm','template',name,str(chart),'--namespace',namespace,'--include-crds','--is-upgrade','--kube-version',version,'--values',str(values)])
        rendered=td/'rendered.yaml';rendered.write_bytes(output);rendered.chmod(0o600)
        for post in spec.get('postRenderers',[]):
            if set(post)!={'kustomize'} or set(post['kustomize'])-{'patches','images'}:raise ValueError('unsupported Helm post renderer')
            k={'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','resources':['rendered.yaml'],**post['kustomize']}
            (td/'kustomization.yaml').write_text(yaml.safe_dump(k,sort_keys=False))
            output=checked_output(['kubectl','kustomize',str(td)])
            rendered.write_bytes(output)
        return normalize([o for o in yaml.safe_load_all(output) if o],namespace)

def compile_all(documents,locks,cache):
    releases={o['metadata']['name']:o for o in documents if o and o.get('kind')=='HelmRelease'}
    sources={o['metadata']['name']:o for o in documents if o and o.get('kind')=='OCIRepository'}
    if set(releases)!=set(locks['releases']):raise ValueError('Helm source/lock release set differs')
    files={};aggregate={'version':1,'executionGroup':'re8ch:release-executor:networking','releases':[],'platformBootstrap':[],'omitted':[],'charts':[]};seen=set()
    for name,lock in sorted(locks['releases'].items()):
        declaration=releases[name];spec=declaration['spec'];chart=lock['chart']
        if spec['targetNamespace']!=lock['namespace'] or spec.get('releaseName',name)!=lock['releaseName']:raise ValueError('Helm target differs from lock')
        if 'oci' in chart:
            source=sources[spec['chartRef']['name']]['spec']
            if chart['oci']!=source['url']+'@'+source['ref']['digest']:raise ValueError('Helm OCI declaration differs from lock')
            context={'revision':'helm-oci@'+chart['oci'].rsplit('@',1)[1],'chartOCI':chart['oci']}
        else:
            if chart['path']!=spec['chart']['spec']['chart'].removeprefix('./'):raise ValueError('vendored chart path differs from lock')
            context={'revision':'helm-archive@sha256:'+chart['sha256'],'chart':chart['path'],'chartDigest':'sha256:'+chart['sha256']}
        restricted=bool(declaration.get('sops') or spec.get('valuesFrom'))
        if restricted!=lock['restricted']:raise ValueError('restricted rendering classification differs from lock')
        if restricted:
            aggregate['omitted'].append({'identity':object_identity(declaration),'reason':'protected-render-required','chart':chart});continue
        objects=render(declaration,fetch_chart(name,lock,cache),locks['kubernetesVersion'])
        runtime=[]
        for o in objects:
            identity=object_identity(o)
            if identity in seen:raise ValueError('Helm ownership overlap: '+identity)
            seen.add(identity)
            if o['kind']=='Secret':aggregate['omitted'].append({'identity':identity,'reason':'preserve-existing-secret'});continue
            if 'helm.sh/hook' in (o['metadata'].get('annotations') or {}):aggregate['omitted'].append({'identity':identity,'reason':'one-shot-helm-hook'});continue
            if not o['metadata'].get('namespace'):
                aggregate['platformBootstrap'].append(o);continue
            runtime.append(o)
        projected,ledger=project(runtime,prefix='networking-helm-'+name,source_context=context)
        projected.pop('operations/releases/native-authority.json')
        files.update(projected)
        for release in ledger['releases']:
            contract=yaml.safe_load(projected[release['contract']]);release['source']=contract['spec']['source']
            release['renderedSHA256']=hashlib.sha256(projected[release['source']['path']+'/resources.yaml'].encode()).hexdigest()
        aggregate['releases'].extend(ledger['releases']);aggregate['platformBootstrap'].extend(ledger['platformBootstrap']);aggregate['omitted'].extend(ledger['omitted'])
        aggregate['charts'].append({'name':name,'chart':chart,'objects':len(objects)})
    native=json.loads((ROOT/'operations/releases/native-authority.json').read_text())
    native_ids={identity for r in native['releases'] for identity in r['inventory']}
    if any(identity in native_ids for r in aggregate['releases'] for identity in r['inventory']):raise ValueError('Helm/native SSA ownership overlap')
    aggregate['platformBootstrap'].sort(key=object_identity)
    files['operations/releases/helm-authority.json']=json.dumps(aggregate,indent=2)+'\n'
    return files,aggregate

def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--cache-dir',type=Path,default=ROOT/'.cache/charts');a=p.parse_args()
    locks=json.loads((ROOT/'operations/releases/helm-lock.json').read_text())
    version=subprocess.check_output(['helm','version','--short'],text=True).strip().split('+')[0]
    if version!=locks['helmVersion']:raise ValueError('Helm compiler version differs from lock')
    documents=list(yaml.safe_load_all(subprocess.check_output(['kubectl','kustomize','clusters/re8ch'],cwd=ROOT)))
    files,ledger=compile_all(documents,locks,a.cache_dir)
    stale=[]
    for name,content in files.items():
        path=ROOT/name
        if a.check:
            if not path.exists() or path.read_text()!=content:stale.append(name)
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
    existing={str(p.relative_to(ROOT)) for p in (ROOT/'contracts').glob('networking-helm-*.yaml')}
    existing|={str(p.relative_to(ROOT)) for p in (ROOT/'releases').glob('networking-helm-*/*') if p.is_file()}
    for name in sorted(existing-set(files)-{'contracts/networking-helm-advanced-fabric-kube-system.yaml'}):
        if a.check:stale.append(name)
        else:(ROOT/name).unlink()
    if stale:raise SystemExit('Helm projection drift: '+', '.join(stale))
    print(json.dumps({'charts':len(ledger['charts']),'releases':len(ledger['releases']),'objects':sum(len(r['inventory']) for r in ledger['releases']),'platformBootstrap':len(ledger['platformBootstrap']),'omitted':len(ledger['omitted'])}))
if __name__=='__main__':main()
