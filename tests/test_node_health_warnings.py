import copy
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'operations/releases'))
from ssa_executor import Executor


def check(ready=True, allowed=True, extra_pod=False, available=1):
    live={'metadata': {'name': 'agent', 'namespace': 'kube-system', 'uid': 'owner'},
          'status': {'desiredNumberScheduled': 2, 'numberAvailable': available}}
    nodes={'items': [node('working', True), node('offline', False)]}
    pods={'items': [pod('working', ready), pod('offline', False)]}
    if extra_pod:
        unrelated=pod('working', True); unrelated['metadata']['ownerReferences'][0]['uid']='other';pods['items'].append(unrelated)
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, json.dumps(nodes if 'nodes' in argv else pods), '')
    ex=Executor(runner=runner);ex.warning_nodes={'offline'} if allowed else set()
    return ex.daemonset_node_health(live)


def node(name, ready):
    return {'metadata': {'name': name}, 'status': {'conditions': [{'type': 'Ready', 'status': str(ready)}]}}


def pod(node, ready):
    return {'metadata': {'ownerReferences': [{'uid': 'owner', 'controller': True}]},
            'spec': {'nodeName': node}, 'status': {'conditions': [{'type': 'Ready', 'status': str(ready)}]}}


def test_explicit_unavailable_node_is_warning():
    healthy, reason=check();assert healthy and reason.startswith('Warning:')


def test_ready_node_failure_is_not_excused():
    assert not check(ready=False)[0]


def test_unapproved_unavailable_node_is_not_excused():
    assert not check(allowed=False)[0]


def test_other_daemonsets_cannot_fill_coverage():
    assert not check(ready=False, extra_pod=True)[0]


def test_additional_unavailable_replicas_are_not_excused():
    assert not check(available=0)[0]
