"""Verify the pinned source and preserve live topology during first adoption.

Only the exact diagnostic ConfigMap and existing AdvancedFabric are read.
Values and differing paths never enter errors, logs, results, or artifacts.
"""
import hashlib
import json

SOURCE_SHA256='0a25eb8106bea53a63730ad08d5dc5be3b14f28103d0b97a4f5aa551a208f7d0'
API='networking.advfab.org/v1alpha1'

class TopologyParityError(ValueError):
    pass

def difference_counts(desired,live):
    counts={'placement':0,'controllerRuntime':0,'virtualIngressRuntime':0,'networkOrOther':0}
    def add(path):
        if len(path)>1 and path[0] in {'controller','virtualIngress'} and path[1] in {'affinity','tolerations'}:category='placement'
        elif path and path[0]=='controller':category='controllerRuntime'
        elif path and path[0]=='virtualIngress':category='virtualIngressRuntime'
        else:category='networkOrOther'
        counts[category]+=1
    def visit(want,actual,path):
        if isinstance(want,dict):
            if not isinstance(actual,dict):add(path);return
            for key,value in want.items():
                if key not in actual:add(path+(key,))
                else:visit(value,actual[key],path+(key,))
        elif isinstance(want,list):
            if not isinstance(actual,list) or len(want)!=len(actual):add(path);return
            for index,(a,b) in enumerate(zip(want,actual)):visit(a,b,path+(str(index),))
        elif type(want)!=type(actual) or want!=actual:add(path)
    visit(desired,live,())
    return counts

def differences(desired,live):return sum(difference_counts(desired,live).values())

def check(objects,previous,command):
    targets=[o for o in objects if o.get('apiVersion')==API and o.get('kind')=='AdvancedFabric']
    if not targets:return None
    if len(targets)!=1 or targets[0]['metadata']['name']!='advanced-fabric' or targets[0]['metadata'].get('namespace'):
        raise TopologyParityError('unreviewed topology identity')
    try:
        result=command(['kubectl','get','configmap','restricted-topology-context','--namespace','ops','-o','json'],timeout=60,redact=True)
        source=json.loads(result.stdout)['data']['bundle.json']
        if hashlib.sha256(source.encode()).hexdigest()!=SOURCE_SHA256:
            raise TopologyParityError('restricted topology source pin mismatch')
        if previous and previous.get('healthyDigest'):
            return {'sourcePinMatches':True,'initialAdoption':False}
        result=command(['kubectl','get','advancedfabrics.networking.advfab.org','advanced-fabric','-o','json'],timeout=60,redact=True)
        live=json.loads(result.stdout)
        version=targets[0]['metadata'].get('resourceVersion')
        if not version or live.get('metadata',{}).get('resourceVersion')!=version:
            raise TopologyParityError('topology changed while binding adoption precondition')
        counts=difference_counts(targets[0]['spec'],live['spec'])
        count=sum(counts.values())
    except TopologyParityError:raise
    except Exception:
        raise TopologyParityError('restricted topology parity could not be verified; diagnostics withheld') from None
    if count:raise TopologyParityError('initial topology adoption differs from live state; difference count='+str(count)+'; categories='+json.dumps(counts,sort_keys=True))
    return {'sourcePinMatches':True,'initialAdoption':True,'differenceCount':0}
