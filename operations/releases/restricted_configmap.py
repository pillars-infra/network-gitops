"""Decrypt authenticated ConfigMap envelopes in memory after artifact verification.

No Secret support, key discovery, filesystem plaintext, or diagnostic forwarding.
The caller supplies an error-redacting command runner and a provisioned key.
"""
import hashlib
import json

class RestrictedConfigError(ValueError):
    pass

def validate_envelope(item):
    if item.get('apiVersion')!='v1' or item.get('kind')!='ConfigMap':
        raise RestrictedConfigError('only ConfigMap envelopes are supported')
    sops=item.get('sops',{})
    if not sops.get('age') or not str(sops.get('mac','')).startswith('ENC[AES256_GCM,'):
        raise RestrictedConfigError('authenticated age envelope is required')
    data=item.get('data',{})
    encrypted=[key for key,value in data.items() if isinstance(value,str) and value.startswith('ENC[AES256_GCM,')]
    if not encrypted or item.get('binaryData'):
        raise RestrictedConfigError('expected encrypted ConfigMap string data')
    try:
        hashes=json.loads(item['metadata']['annotations']['security.re8ch.com/restricted-data-sha256'])
        if set(hashes)!=set(encrypted) or any(len(v)!=64 for v in hashes.values()):raise ValueError()
    except (ValueError,KeyError,TypeError):
        raise RestrictedConfigError('complete plaintext parity digests are required') from None
    return hashes

SOURCE_FIELD='_re8chSopsSource'

def bind_source(item, original=None):
    """Keep SOPS traversal order inside the signed canonical JSON artifact."""
    if original is None:original={k:v for k,v in item.items() if k!=SOURCE_FIELD}
    source=item.get(SOURCE_FIELD,json.dumps(original,separators=(',',':')))
    try:
        if json.loads(source)!={k:v for k,v in item.items() if k!=SOURCE_FIELD}:raise ValueError()
    except (ValueError,TypeError):
        raise RestrictedConfigError('serialized SOPS source differs from signed envelope') from None
    return {**item,SOURCE_FIELD:source}

def decrypt_configmap(item,command):
    hashes=validate_envelope(item)
    if SOURCE_FIELD not in item:raise RestrictedConfigError('ordered SOPS source is required')
    item=bind_source(item)
    source=item.pop(SOURCE_FIELD)
    result=command(['sops','--decrypt','--input-type','json','--output-type','json','/dev/stdin'],source,timeout=60,redact=True)
    try:
        if len(result.stdout)>10*1024*1024:raise ValueError()
        plain=json.loads(result.stdout)
        original={k:v for k,v in item.items() if k not in {'data','sops'}}
        observed={k:v for k,v in plain.items() if k!='data'}
        if original!=observed or set(plain['data'])!=set(item['data']):raise ValueError()
        for key,want in hashes.items():
            if hashlib.sha256(plain['data'][key].encode()).hexdigest()!=want:raise ValueError()
        for key,value in item['data'].items():
            if key not in hashes and plain['data'][key]!=value:raise ValueError()
        return plain
    except (ValueError,KeyError,TypeError,AttributeError):
        raise RestrictedConfigError('decrypted ConfigMap identity or parity mismatch') from None
