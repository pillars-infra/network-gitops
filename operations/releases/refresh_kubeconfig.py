#!/usr/bin/env python3
"""Renew the current executor credential without passing secrets in process argv."""
import os
import argparse
from pathlib import Path
import tempfile

import yaml

from ssa_executor import Executor, Rejected
from kube_endpoint import base_config, select


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
    current = config.get('current-context')
    contexts = [item for item in config.get('contexts', []) if item.get('name') == current]
    cluster = contexts[0].get('context', {}).get('cluster') if len(contexts) == 1 else None
    if cluster in {'re8ch', 're8ch-main', 're8ch-atlantic'}:
        select(path, config, cluster)


def initialize() -> None:
    """Create the fixed cluster config privately, then use the guarded OIDC client."""
    path = Path(os.environ['KUBECONFIG'])
    ca = os.environ['KUBE_API_CA_PEM']
    if not ca.strip():
        raise Rejected('missing Kubernetes API CA')
    config = base_config('re8ch-main', '', ca)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    refresh()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--initialize',action='store_true')
    args=parser.parse_args()
    initialize() if args.initialize else refresh()
