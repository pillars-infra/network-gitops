#!/usr/bin/env python3
"""Project the existing Kustomize root into bounded SSA releases.

This compiler never decrypts or reads Kubernetes. Public artifacts only contain
reviewed plaintext native objects. Every omitted object remains explicit.
"""
import argparse
import copy
import ipaddress
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import yaml
from unified_bundle import api_group, canonical, compile_bundle, digest, object_identity, assert_pinned_images
from operation_materialize import state_configmap_name
from restricted_configmap import validate_envelope, bind_source
from profile import REPOSITORY, WORKFLOW, ENVIRONMENT, AUDIENCE, SIGNER, CLOUD_CANARY_RELEASES
ROOT=Path(__file__).resolve().parents[2]
PLURALS={'NetworkPolicy':'networkpolicies','CiliumNetworkPolicy':'ciliumnetworkpolicies','PeerPolicy':'peerpolicies','BackendTLSPolicy':'backendtlspolicies','Ingress':'ingresses'}
KUBE_API_RELEASE_OBJECTS={
    'core/ConfigMap/kube-system/kube-api-observer-proxy',
    'apps/Deployment/kube-system/kube-api-observer-proxy',
    'core/Service/kube-system/kube-api-observer-proxy',
    'gateway.networking.k8s.io/BackendTLSPolicy/kube-system/kube-api-observer-proxy',
    'gateway.networking.k8s.io/HTTPRoute/kube-system/kube-api-service',
}
DEDICATED_NATIVE_RELEASES={
    'core/ConfigMap/egress-fabric/mihomos-node-configs': 'networking-native-mihomo-routing',
    'core/Service/egress-fabric/mihomos-global-exit-atlantic': 'networking-native-mihomo-routing',
}
# Reviewed bootstrap bridge adopted in place by the existing ImportedService.
# Keep the source as migration evidence, but never statically reapply its result.
CONTROLLER_OWNED_RUNTIME_RESULTS={
    'core/Service/byoc-pilot/re8ch-atlantic-default-kubernetes-re8ch-atlantic':
        'atlantic-kubernetes-import.among-clusters.svc.cluster.local',
}
OBSERVED_READINESS_RELEASES={
    'networking-helm-cilium-kube-system',
    'networking-native-kube-system',
}
EXTERNAL_NATIVE_RELEASES={
    'networking-native-self-cloud-target-canary',
    'networking-native-atlantic-cloud-target-canary',
    'networking-native-atlantic-bootstrap',
    'networking-native-atlantic-among-clusters',
    'networking-native-atlantic-mihomo-global-exit',
    'networking-native-atlantic-personal-access',
    'networking-native-atlantic-kubernetes-advertisement',
    'networking-native-atlantic-mail-system',
}

CLOUD_STATE_BOOTSTRAP={
    'core/ConfigMap/default/'+state_configmap_name(name) for name in CLOUD_CANARY_RELEASES
}

def classify(document):
    identity=object_identity(document)
    if identity in CLOUD_STATE_BOOTSTRAP:
        if document.get('data',{}) != {}:
            raise ValueError('bootstrap state declaration must not contain runtime acceptance')
        return 'platform-bootstrap-state'
    if identity in CONTROLLER_OWNED_RUNTIME_RESULTS:
        spec=document.get('spec',{})
        if spec.get('type')!='ExternalName' or spec.get('externalName')!=CONTROLLER_OWNED_RUNTIME_RESULTS[identity]:
            raise ValueError('reviewed controller-owned bridge differs from bootstrap source')
        return 'controller-owned-runtime-result'
    if 'sops' in document:
        if document['kind']!='ConfigMap':return 'restricted-sops'
        validate_envelope(document)
    if document['kind']=='Secret':return 'secret'
    if document['kind']=='Job':return 'one-shot-operation'
    if document['kind'] in {'Role','RoleBinding','ClusterRole','ClusterRoleBinding'}:return 'platform-bootstrap-rbac'
    if document['kind'] in {'HelmRelease','HelmChart'}:return 'cloud-helm-render'
    if document['apiVersion'].split('/')[0] in {'source.toolkit.fluxcd.io','kustomize.toolkit.fluxcd.io','helm.toolkit.fluxcd.io','notification.toolkit.fluxcd.io','image.toolkit.fluxcd.io'}:return 'flux-source-metadata'
    if not document['metadata'].get('namespace'):return 'cluster-network-authority'
    try:assert_pinned_images(document)
    except ValueError:return 'image-digest-required'
    return None

def resolve_routeros_pool_policy(documents):
    """Resolve reviewed pool references in the existing native projection.

    Kustomize cannot project another object's fields into a JSON-valued
    ConfigMap entry. Reuse this compiler; do not duplicate allocation state.
    """
    documents = copy.deepcopy(documents)
    pools = {d['metadata']['name']: d for d in documents if d and d.get('kind') == 'CiliumPodIPPool'}
    for d in documents:
        if not d or object_identity(d) != 'core/ConfigMap/ops/routeros-public-forward-controller':
            continue
        desired = json.loads(d['data']['desired.json'])
        policy = desired.get('podReturnPolicy')
        if not policy:
            continue
        refs = policy.get('poolRefs', [])
        if not refs or len(set(refs)) != len(refs):
            raise ValueError('unique RouterOS pool references are required')
        approved, networks = [], []
        for ref in sorted(refs):
            pool = pools.get(ref)
            if not pool or pool.get('apiVersion') != 'cilium.io/v2alpha1':
                raise ValueError('referenced CiliumPodIPPool is unavailable')
            ipv4 = pool.get('spec', {}).get('ipv4', {})
            if ipv4.get('maskSize') != 24 or not ipv4.get('cidrs'):
                raise ValueError('reviewed IPv4 /24 allocation pool is required')
            for cidr in sorted(ipv4['cidrs']):
                network = ipaddress.ip_network(cidr, strict=True)
                if network.version != 4 or not network.subnet_of(ipaddress.ip_network('10.64.0.0/12')) or network.prefixlen > 24 or any(network.overlaps(prior) for prior in networks):
                    raise ValueError('invalid or overlapping native Pod pool')
                networks.append(network)
                approved.append({'poolRef': ref, 'cidr': str(network), 'maskSize': 24})
        policy['approvedPools'] = approved
        d['data']['desired.json'] = json.dumps(desired, indent=2) + '\n'
    return documents


def project(documents, prefix="networking-native", source_context=None):
    documents = resolve_routeros_pool_policy(documents)
    groups=defaultdict(list); omitted=[]; bootstrap=[]
    for d in documents:
        if not d:continue
        reason=classify(d)
        if reason:
            omitted.append({'identity':object_identity(d),'reason':reason})
            if reason in {'platform-bootstrap-rbac','platform-bootstrap-state'}:bootstrap.append(d)
            continue
        namespace=d['metadata']['namespace']
        identity=object_identity(d)
        if prefix=='networking-native' and identity in KUBE_API_RELEASE_OBJECTS:
            name='networking-native-kube-api'
        elif prefix=='networking-native' and identity in DEDICATED_NATIVE_RELEASES:
            name=DEDICATED_NATIVE_RELEASES[identity]
        else:
            name=prefix+'-'+namespace
        groups[(name,namespace)].append(d)
    files={};releases=[]
    # This singleton ConfigMap is itself the bootstrap authority consumed by
    # networking controllers.  Unlike ordinary adopted native objects, the
    # protected release must be able to recreate it after accidental deletion.
    recreatable_releases={'networking-native-flux-network-system'}
    for (name,namespace),objects in sorted(groups.items()):
        objects.sort(key=object_identity);folder=f'releases/{name}'
        inventory=sorted(object_identity(o) for o in objects)
        lifecycle={'prune':False,'healthTimeoutSeconds':300,'protectedKinds':['Namespace','CustomResourceDefinition','PersistentVolume','PersistentVolumeClaim','StorageClass'],'deletionAllowlist':[]}
        if name in OBSERVED_READINESS_RELEASES:lifecycle['readinessPolicy']='observe'
        if name in {'networking-native-kube-system', 'networking-native-ops', 'networking-helm-public-edge-manager-regional-routing'}:
            # Projected scripts and envFrom are consumed at process startup. A
            # workload checksum is not proof its ConfigMap was installed first.
            lifecycle['stages'] = [
                {'name': 'configuration', 'kinds': ['ConfigMap']},
                {'name': 'runtime', 'kinds': sorted({o['kind'] for o in objects} - {'ConfigMap'})},
            ]
        contract={'apiVersion':'delivery.re8ch.com/v1alpha1','kind':'ReleaseContract','metadata':{'name':name},'spec':{
            'authorityDomain':'networking','target':{'cluster':'re8ch','namespace':namespace},
            'source':{'renderer':'kustomize','revision':'github-main-reviewed','repository':REPOSITORY,'path':folder,**(source_context or {})},
            'provenance':{'repository':REPOSITORY,'workflow':WORKFLOW,'ref':'refs/heads/main','environment':ENVIRONMENT,'audience':AUDIENCE,'signer':SIGNER,'issuer':'https://token.actions.githubusercontent.com'},
            'authorization':{'requireExisting':name not in recreatable_releases,'fieldManager':'re8ch-release/'+name,'resources':sorted({api_group(o['apiVersion'])+'/'+o['kind'] for o in objects}),'objectNames':sorted({o['metadata']['name'] for o in objects}),'forceConflictObjects':inventory},
            'inventory':{'digest':digest(canonical(inventory))},
            'lifecycle':lifecycle}}
        rendered=yaml.safe_dump_all(objects,sort_keys=False)
        compile_bundle(contract,rendered.encode()) # Validate identity, pinning and envelope before emitting.
        files[f'contracts/{name}.yaml']=yaml.safe_dump(contract,sort_keys=False)
        files[f'{folder}/resources.yaml']=rendered
        files[f'{folder}/kustomization.yaml']='apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources: [resources.yaml]\n'
        permissions=defaultdict(set)
        for o in objects:permissions[(api_group(o['apiVersion']),PLURALS.get(o['kind'],o['kind'].lower()+'s'))].add(o['metadata']['name'])
        rules=[{'apiGroups':['' if group=='core' else group],'resources':[resource],'resourceNames':sorted(names),'verbs':['get','patch']} for (group,resource),names in sorted(permissions.items())]
        if name in recreatable_releases:
            # Kubernetes cannot authorize create by resourceName because the
            # object does not exist yet.  The signed ReleaseContract supplies
            # the exact-name guard before this namespace-scoped verb is used.
            rules.append({'apiGroups':[''],'resources':['configmaps'],'verbs':['create']})
        state=state_configmap_name(name)
        rules.append({'apiGroups':[''],'resources':['configmaps'],'resourceNames':[state],'verbs':['get','patch']})
        releases.append({'releaseId':name,'contract':f'contracts/{name}.yaml','namespace':namespace,'inventory':inventory,'rules':rules,'stateConfigMap':{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':state,'namespace':namespace},'data':{}}})
    ledger={'version':1,'source':'clusters/re8ch','executionGroup':'re8ch:release-executor:networking','verbsNote':'Existing-object adoption uses get/patch only. The singleton cluster-node-inventory bootstrap release also receives create so it can recover its exact reviewed ConfigMap; its contract still constrains namespace, kind and object name. Delete, Secret reads, impersonation and token minting are not granted. Role/RoleBinding objects remain platform-owned and are listed under platformBootstrap; no bind/escalate authority is requested.','releases':releases,'platformBootstrap':sorted(bootstrap,key=object_identity),'omitted':sorted(omitted,key=lambda x:x['identity'])}
    files['operations/releases/native-authority.json']=json.dumps(ledger,indent=2)+'\n'
    return files,ledger

def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
    rendered=subprocess.check_output(['kubectl','kustomize','clusters/re8ch'],cwd=ROOT)
    originals={object_identity(d):d for path in (ROOT/'clusters/re8ch').glob('*.yaml') for d in yaml.safe_load_all(path.read_text()) if isinstance(d,dict) and 'sops' in d}
    documents=list(yaml.safe_load_all(rendered))
    for index,d in enumerate(documents):
        if d and 'sops' in d and d.get('kind')=='ConfigMap':
            documents[index]=bind_source(d, originals[object_identity(d)])
    files,ledger=project(documents)
    # Keep the static Kustomize view coherent as well as the native release.
    # The generated array is a projection of poolRefs, never another IPAM source.
    resolved = resolve_routeros_pool_policy(documents)
    source_path = ROOT/'clusters/re8ch/routeros-public-forward-controller.yaml'
    source_text = source_path.read_text()
    source_cm = next(d for d in yaml.safe_load_all(source_text) if d and d.get('kind') == 'ConfigMap')
    resolved_cm = next((d for d in resolved if d and object_identity(d) == 'core/ConfigMap/ops/routeros-public-forward-controller'), None)
    if resolved_cm and source_cm['data']['desired.json'] != resolved_cm['data']['desired.json']:
        old = ''.join('    '+line+'\n' for line in source_cm['data']['desired.json'].splitlines())
        new = ''.join('    '+line+'\n' for line in resolved_cm['data']['desired.json'].splitlines())
        if source_text.count(old) != 1:
            raise ValueError('RouterOS static pool projection anchor differs')
        files['clusters/re8ch/routeros-public-forward-controller.yaml'] = source_text.replace(old, new)
    stale=[]
    for name,content in files.items():
        path=ROOT/name
        if args.check:
            if not path.exists() or path.read_text()!=content:stale.append(name)
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
    existing={str(p.relative_to(ROOT)) for p in (ROOT/'contracts').glob('networking-native-*.yaml')}
    existing|={str(p.relative_to(ROOT)) for p in (ROOT/'releases').glob('networking-native-*/*') if p.is_file()}
    obsolete=sorted(name for name in existing-set(files)
                    if not any(f'/{release}' in name for release in EXTERNAL_NATIVE_RELEASES))
    if args.check:stale.extend(obsolete)
    else:
        for name in obsolete:(ROOT/name).unlink()
    if stale:raise SystemExit('native projection drift: '+', '.join(stale))
    print(json.dumps({'releases':len(ledger['releases']),'objects':sum(len(r['inventory']) for r in ledger['releases']),'omitted':len(ledger['omitted'])}))
if __name__=='__main__':main()
