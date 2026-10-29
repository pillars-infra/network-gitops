#!/usr/bin/env python3
"""Renew the current executor credential without passing secrets in process argv."""
import os
import argparse
import base64
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


def initialize() -> None:
    """Create the fixed cluster config privately, then use the guarded OIDC client."""
    path = Path(os.environ['KUBECONFIG'])
    ca = os.environ['KUBE_API_CA']
    if not ca.strip():
        raise Rejected('missing Kubernetes CA')
    config = {'apiVersion':'v1','kind':'Config',
              'clusters':[{'name':'re8ch-main','cluster':{'server':'https://kube-api.service.re8ch.com', 'tls-server-name':'kube-api.re8ch.com',
                           'certificate-authority-data':base64.b64encode(ca.encode()).decode()}}],
              'users':[{'name':'release-executor','user':{}}],
              'contexts':[{'name':'release-executor','context':{'cluster':'re8ch-main','user':'release-executor'}}],
              'current-context':'release-executor'}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    refresh()


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--initialize',action='store_true')
    args=parser.parse_args()
    initialize() if args.initialize else refresh()
