import copy
import hashlib
import json
import subprocess

import pytest

import topology_parity
from ssa_executor import Executor, Rejected


def test_initial_adoption_rechecks_spec_and_rebinds_each_conflicted_apply(monkeypatch):
    monkeypatch.setattr(topology_parity, 'SOURCE_SHA256', hashlib.sha256(b'fixture').hexdigest())
    desired = {'apiVersion': topology_parity.API, 'kind': 'AdvancedFabric',
               'metadata': {'name': 'advanced-fabric', 'uid': 'same-object'},
               'spec': {'nodes': [{'name': 'private-fixture'}]}}
    reads = 0
    applies = []

    def runner(argv, **kwargs):
        nonlocal reads
        if argv[1] == 'get':
            if argv[2] == 'configmap':
                return subprocess.CompletedProcess(argv, 0, json.dumps({'data': {'bundle.json': 'fixture'}}), '')
            if argv[-1].startswith('jsonpath='):
                return subprocess.CompletedProcess(argv, 0, 'earlier-version', '')
            reads += 1
            live = copy.deepcopy(desired)
            live['metadata']['resourceVersion'] = str(reads)
            # A real spec change after the first conflict must abort, even though
            # ordinary status-only changes and versions are expected to advance.
            if reads > 1:
                live['spec']['nodes'] = []
            return subprocess.CompletedProcess(argv, 0, json.dumps(live), '')
        applies.append(json.loads(kwargs['input']))
        return subprocess.CompletedProcess(argv, 1, '', 'the object has been modified: private-fixture')

    executor = Executor(runner=runner, sleeper=lambda _: None)
    executor._initial_topology_adoption = True
    executor._restricted_identities.add('networking.advfab.org/AdvancedFabric/_/advanced-fabric')
    with pytest.raises(Rejected, match='difference count=1'):
        executor.apply([desired], 'fixture', False, rebind_existing=True)
    assert reads == 2 and len(applies) == 1
    assert applies[0]['metadata']['resourceVersion'] == '1'
    assert applies[0]['metadata']['uid'] == 'same-object'


def test_restricted_failure_exposes_only_fixed_classification():
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, 'private-stdout',
                                           'conflict with private-manager: private-field and private-value')
    with pytest.raises(Rejected) as exc:
        Executor(runner=runner).command(['kubectl', 'apply'], redact=True)
    assert str(exc.value) == 'restricted command failed; category=field-ownership-conflict; diagnostics withheld'
