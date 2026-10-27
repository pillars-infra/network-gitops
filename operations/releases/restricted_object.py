"""Opaque, signed, order-preserving envelopes for reviewed Helm runtime objects."""
import copy
import json
from restricted_configmap import RestrictedConfigError
from unified_bundle import assert_pinned_images
FIELD='_re8chRestrictedPayload'
ALLOWED={'v1/ConfigMap','v1/Service','v1/ServiceAccount','apps/v1/Deployment','apps/v1/DaemonSet','policy/v1/PodDisruptionBudget','cert-manager.io/v1/Certificate','cert-manager.io/v1/Issuer','networking.k8s.io/v1/IngressClass','networking.advfab.org/v1alpha1/AdvancedFabric'}

def identity(item):
    return {'apiVersion':item['apiVersion'],'kind':item['kind'],'metadata':{key:copy.deepcopy(item['metadata'][key]) for key in ('name','namespace') if key in item['metadata']}}

def validate(item):
    if item['apiVersion']+'/'+item['kind'] not in ALLOWED:raise RestrictedConfigError('unsupported restricted Helm resource')
    if set(item)!={'apiVersion','kind','metadata',FIELD}:raise RestrictedConfigError('restricted object must contain only identity and ciphertext')
    if item['metadata']!=identity(item)['metadata']:raise RestrictedConfigError('restricted envelope metadata must be identity only')
    wrapper=json.loads(item[FIELD])
    if not wrapper.get('sops',{}).get('age') or not wrapper['sops'].get('mac','').startswith('ENC[AES256_GCM,') or not wrapper.get('payload','').startswith('ENC[AES256_GCM,'):
        raise RestrictedConfigError('authenticated encrypted payload is required')

def seal(item,recipient,command):
    assert_pinned_images(item)
    outer=identity(item)
    if item['apiVersion']+'/'+item['kind'] not in ALLOWED:raise RestrictedConfigError('unsupported restricted Helm resource')
    payload=json.dumps(item,separators=(',',':'))
    encrypted=command(['sops','--encrypt','--age',recipient,'--encrypted-regex','^payload$','--input-type','json','--output-type','json','/dev/stdin'],json.dumps({'payload':payload}),redact=True)
    outer[FIELD]=encrypted.stdout
    validate(outer)
    return outer

def decrypt(item,command):
    validate(item)
    result=command(['sops','--decrypt','--input-type','json','--output-type','json','/dev/stdin'],item[FIELD],redact=True)
    try:
        if len(result.stdout)>10*1024*1024:raise ValueError()
        plain=json.loads(json.loads(result.stdout)['payload'])
        if identity(plain)!=identity(item) or 'sops' in plain or FIELD in plain:raise ValueError()
        assert_pinned_images(plain)
        return plain
    except (ValueError,KeyError,TypeError):
        raise RestrictedConfigError('restricted Helm payload identity or pinning mismatch') from None
