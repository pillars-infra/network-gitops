#!/usr/bin/env python3
"""Renew the current executor credential without passing secrets in process argv."""
import os
from pathlib import Path
import tempfile

import yaml

from ssa_executor import Executor, Rejected


def refresh() -> None:
    path = Path(os.environ['KUBECONFIG'])
    if path.is_symlink() or not path.is_file():
        raise Rejected('expected one regular executor kubeconfig')
    config = yaml.safe_load(path.read_text())
    matches = [entry for entry in config.get('users', []) if entry.get('name') == 'release-executor']
    if len(matches) != 1:
        raise Rejected('expected exactly one release-executor credential')
    token = Executor().actions_kube_token()
    if not isinstance(token, str) or not token:
        raise Rejected('Actions OIDC returned no executor credential')
    matches[0]['user'] = {'token': token}
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            yaml.safe_dump(config, handle, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == '__main__':
    refresh()
