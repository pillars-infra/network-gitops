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

def differences(desired,live):
    if isinstance(desired,dict):
        if not isinstance(live,dict):return 1
        return sum(1 if key not in live else differences(value,live[key]) for key,value in desired.items())
    if isinstance(desired,list):
        if not isinstance(live,list) or len(desired)!=len(live):return 1
        return sum(differences(a,b) for a,b in zip(desired,live))
    return int(type(desired)!=type(live) or desired!=live)

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
        count=differences(targets[0]['spec'],live['spec'])
    except TopologyParityError:raise
    except Exception:
        raise TopologyParityError('restricted topology parity could not be verified; diagnostics withheld') from None
    if count:raise TopologyParityError('initial topology adoption differs from live state; difference count='+str(count))
    return {'sourcePinMatches':True,'initialAdoption':True,'differenceCount':0}
