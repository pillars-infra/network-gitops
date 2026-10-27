"""Bind adoption writes to existing Kubernetes object resource versions.

The signed contract opts in. The runtime snapshot is never added to the signed
artifact; its resourceVersion is a precondition on both SSA dry-run and apply.
"""
import json
import subprocess

class ExistingObjectError(ValueError):
    pass

def bind_existing(objects, command):
    bound=json.loads(json.dumps(objects))
    for item in bound:
        metadata=item['metadata'];api=item['apiVersion']
        resource=item['kind']+('.'+api.split('/',1)[0] if '/' in api else '')
        argv=['kubectl','get',resource,metadata['name']]
        if metadata.get('namespace'):argv+=['--namespace',metadata['namespace']]
        argv+=['-o','jsonpath={.metadata.resourceVersion}']
        try:
            result=command(argv,timeout=60)
            version=result.stdout.strip()
            if result.returncode or not version or len(version)>1024 or any(c.isspace() for c in version):
                raise ValueError()
        except (OSError,subprocess.SubprocessError,ValueError):
            identity=f"{api}/{item['kind']}/{metadata.get('namespace','_')}/{metadata['name']}"
            raise ExistingObjectError('existing-only adoption could not bind '+identity) from None
        metadata['resourceVersion']=version
    return bound
