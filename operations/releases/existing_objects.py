"""Bind adoption writes to the original object's UID and current resourceVersion.

Runtime metadata never enters the signed artifact. Each write refreshes only the
version; the first observed UID stays fixed to reject deletion and replacement.
"""
import json
import subprocess


class ExistingObjectError(ValueError):
    pass


def bind_existing(objects, command):
    bound = json.loads(json.dumps(objects))
    for item in bound:
        metadata = item['metadata']
        api = item['apiVersion']
        resource = item['kind'] + ('.' + api.split('/', 1)[0] if '/' in api else '')
        argv = ['kubectl', 'get', resource, metadata['name']]
        if metadata.get('namespace'):
            argv += ['--namespace', metadata['namespace']]
        argv += ['-o', 'jsonpath={.metadata.uid}{" "}{.metadata.resourceVersion}']
        try:
            result = command(argv, timeout=60)
            uid, version = result.stdout.strip().split()
            if result.returncode or not uid or not version or len(uid) > 1024 or len(version) > 1024:
                raise ValueError()
            if metadata.get('uid') and metadata['uid'] != uid:
                raise ValueError()
        except (OSError, subprocess.SubprocessError, ValueError):
            identity = f"{api}/{item['kind']}/{metadata.get('namespace', '_')}/{metadata['name']}"
            raise ExistingObjectError('existing-only adoption missing or replaced object: ' + identity) from None
        metadata['uid'] = uid
        metadata['resourceVersion'] = version
    return bound
