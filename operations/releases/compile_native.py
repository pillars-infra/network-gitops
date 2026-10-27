#!/usr/bin/env python3
"""Project the existing Kustomize root into bounded SSA releases.

This compiler never decrypts or reads Kubernetes. Public artifacts only contain
reviewed plaintext native objects. Every omitted object remains explicit.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import yaml
from unified_bundle import api_group, canonical, compile_bundle, digest, object_identity, assert_pinned_images
from operation_materialize import state_configmap_name
from restricted_configmap import validate_envelope
from profile import REPOSITORY, WORKFLOW, ENVIRONMENT, AUDIENCE, SIGNER
ROOT=Path(__file__).resolve().parents[2]
PLURALS={'NetworkPolicy':'networkpolicies','CiliumNetworkPolicy':'ciliumnetworkpolicies','PeerPolicy':'peerpolicies','Ingress':'ingresses'}

def classify(document):
    if 'sops' in document:
        if document['kind']!='ConfigMap':return 'restricted-sops'
        validate_envelope(document)
    if document['kind']=='Secret':return 'secret'
    if document['kind'] in {'Role','RoleBinding'}:return 'platform-bootstrap-rbac'
    if document['kind'] in {'HelmRelease','HelmChart'}:return 'cloud-helm-render'
    if document['apiVersion'].split('/')[0] in {'source.toolkit.fluxcd.io','kustomize.toolkit.fluxcd.io','helm.toolkit.fluxcd.io','notification.toolkit.fluxcd.io','image.toolkit.fluxcd.io'}:return 'flux-source-metadata'
    if not document['metadata'].get('namespace'):return 'cluster-network-authority'
    try:assert_pinned_images(document)
    except ValueError:return 'image-digest-required'
    return None

def project(documents):
    groups=defaultdict(list); omitted=[]; bootstrap=[]
    for d in documents:
        if not d:continue
        reason=classify(d)
        if reason:
            omitted.append({'identity':object_identity(d),'reason':reason})
            if reason=='platform-bootstrap-rbac':bootstrap.append(d)
            continue
        groups[d['metadata']['namespace']].append(d)
    files={};releases=[]
    for namespace,objects in sorted(groups.items()):
        objects.sort(key=object_identity);name='networking-native-'+namespace;folder=f'releases/{name}'
        inventory=sorted(object_identity(o) for o in objects)
        contract={'apiVersion':'delivery.re8ch.com/v1alpha1','kind':'ReleaseContract','metadata':{'name':name},'spec':{
            'authorityDomain':'networking','target':{'cluster':'re8ch','namespace':namespace},
            'source':{'renderer':'kustomize','revision':'github-main-reviewed','repository':REPOSITORY,'path':folder},
            'provenance':{'repository':REPOSITORY,'workflow':WORKFLOW,'ref':'refs/heads/main','environment':ENVIRONMENT,'audience':AUDIENCE,'signer':SIGNER,'issuer':'https://token.actions.githubusercontent.com'},
            'authorization':{'fieldManager':'re8ch-release/'+name,'resources':sorted({api_group(o['apiVersion'])+'/'+o['kind'] for o in objects}),'objectNames':sorted({o['metadata']['name'] for o in objects}),'forceConflictObjects':inventory},
            'inventory':{'digest':digest(canonical(inventory))},
            'lifecycle':{'prune':False,'healthTimeoutSeconds':300,'protectedKinds':['Namespace','CustomResourceDefinition','PersistentVolume','PersistentVolumeClaim','StorageClass'],'deletionAllowlist':[]}}}
        rendered=yaml.safe_dump_all(objects,sort_keys=False)
        compile_bundle(contract,rendered.encode()) # Validate identity, pinning and envelope before emitting.
        files[f'contracts/{name}.yaml']=yaml.safe_dump(contract,sort_keys=False)
        files[f'{folder}/resources.yaml']=rendered
        files[f'{folder}/kustomization.yaml']='apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [resources.yaml]\n'
        permissions=defaultdict(set)
        for o in objects:permissions[(api_group(o['apiVersion']),PLURALS.get(o['kind'],o['kind'].lower()+'s'))].add(o['metadata']['name'])
        rules=[{'apiGroups':['' if group=='core' else group],'resources':[resource],'resourceNames':sorted(names),'verbs':['get','patch']} for (group,resource),names in sorted(permissions.items())]
        state=state_configmap_name(name)
        rules.append({'apiGroups':[''],'resources':['configmaps'],'resourceNames':[state],'verbs':['get','patch']})
        releases.append({'releaseId':name,'contract':f'contracts/{name}.yaml','namespace':namespace,'inventory':inventory,'rules':rules,'stateConfigMap':{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':state,'namespace':namespace},'data':{}}})
    ledger={'version':1,'source':'clusters/re8ch','executionGroup':'re8ch:release-executor:networking','verbsNote':'Existing-object adoption uses get/patch only; create/delete, Secret reads, impersonation and token minting are not granted. Role/RoleBinding objects remain platform-owned and are listed under platformBootstrap; no bind/escalate authority is requested.','releases':releases,'platformBootstrap':sorted(bootstrap,key=object_identity),'omitted':sorted(omitted,key=lambda x:x['identity'])}
    files['operations/releases/native-authority.json']=json.dumps(ledger,indent=2)+'\n'
    return files,ledger

def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    rendered=subprocess.check_output(['kubectl','kustomize','clusters/re8ch'],cwd=ROOT)
    files,ledger=project(list(yaml.safe_load_all(rendered)))
    stale=[]
    for name,content in files.items():
        path=ROOT/name
        if args.check:
            if not path.exists() or path.read_text()!=content:stale.append(name)
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
    existing={str(p.relative_to(ROOT)) for p in (ROOT/'contracts').glob('networking-native-*.yaml')}
    existing|={str(p.relative_to(ROOT)) for p in (ROOT/'releases').glob('networking-native-*/*') if p.is_file()}
    obsolete=sorted(existing-set(files))
    if args.check:stale.extend(obsolete)
    else:
        for name in obsolete:(ROOT/name).unlink()
    if stale:raise SystemExit('native projection drift: '+', '.join(stale))
    print(json.dumps({'releases':len(ledger['releases']),'objects':sum(len(r['inventory']) for r in ledger['releases']),'omitted':len(ledger['omitted'])}))
if __name__=='__main__':main()
