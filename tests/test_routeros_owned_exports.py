"""Use the actual shipped shell/jq ledger path before rendering RouterOS exports."""
import json
import pytest
from test_podcidr_owned_prefixes import node, ledger, run_helper

VIP = '10.251.0.4/32'
PROGRAM = '''
routeros_peer=192.168.88.1
node='{"serviceVipExports":["10.251.0.4/32"]}'
routeros_boundary_owned_prefix_lines
commit_owned_prefix_reconciliation
'''


def previous(prefixes, **kw):
    return ledger(prefixes, **kw) | {'nodeName': 'r640'}


def run(tmp_path, snapshot, before=None, desired='10.42.6.0/24\n10.68.9.0/24\n10.68.22.0/24', program=PROGRAM):
    return run_helper(tmp_path, snapshot, before, desired=desired, node_name='r640', program=program)


def permits(output):
    return [line.rsplit(' permit ', 1)[1] for line in output.splitlines() if ' permit ' in line]


def test_all_current_owned_allocations_export_and_vip_is_preserved(tmp_path):
    result, state, _ = run(tmp_path, [node('r640', ['10.68.9.0/24', '10.68.22.0/24'])])
    assert result.returncode == 0, result.stderr
    assert set(permits(result.stdout)) == {'10.42.6.0/24', '10.68.9.0/24', '10.68.22.0/24', VIP}
    assert result.stdout.splitlines()[0] == 'no ip prefix-list ROS-R640-SERVICE-OUT'
    assert result.stdout.splitlines()[-1].endswith('deny any')
    assert state['nodeName'] == 'r640' and state['ownerNodeUID'] == 'kube-node-uid'
    sequences = [line.split(' seq ')[1].split()[0] for line in result.stdout.splitlines() if ' seq ' in line]
    assert len(set(sequences)) == len(sequences)


def test_reassignment_full_replacement_withdraws_retired_export(tmp_path):
    before = previous(['10.42.6.0/24', '10.68.9.0/24', '10.68.22.0/24'])
    snapshot = [node('r640', ['10.68.9.0/24', '10.68.23.0/24']), node('other', ['10.68.22.0/24'])]
    result, state, _ = run(tmp_path, snapshot, before, desired='10.42.6.0/24\n10.68.9.0/24\n10.68.23.0/24')
    assert result.returncode == 0, result.stderr
    assert '10.68.22.0/24' not in permits(result.stdout)
    assert set(permits(result.stdout)) == {'10.42.6.0/24', '10.68.9.0/24', '10.68.23.0/24', VIP}
    assert '10.68.22.0/24' not in state['prefixes']


@pytest.mark.parametrize('snapshot', [[], [node('r640', missing=True)],
    [node('r640', ['10.68.9.0/24']), node('other', ['10.68.9.0/24'])]])
def test_unknown_or_conflicting_snapshot_keeps_last_known_exports(tmp_path, snapshot):
    before = previous(['10.42.6.0/24', '10.68.9.0/24', '10.68.22.0/24'])
    result, state, _ = run(tmp_path, snapshot, before, desired='10.42.6.0/24')
    assert result.returncode == 0, result.stderr
    assert set(permits(result.stdout)) == set(before['prefixes']) | {VIP}
    assert state == before


def test_authoritative_empty_withdraws_pool_exports_but_keeps_vip(tmp_path):
    result, state, _ = run(tmp_path, [node('r640', [])], previous(['10.68.9.0/24']), desired='')
    assert result.returncode == 0, result.stderr
    assert permits(result.stdout) == [VIP]
    assert state['prefixes'] == []


def test_kubernetes_node_identity_change_blocks_export_and_ledger_write(tmp_path):
    before = previous(['10.68.9.0/24']) | {'ownerNodeUID': 'different-kubernetes-node'}
    result, state, _ = run(tmp_path, [node('r640', ['10.68.9.0/24'])], before)
    assert result.returncode != 0
    assert result.stdout == '' and state == before


@pytest.mark.parametrize('desired', ['10.68.999.0/24', '10.68.9.1/24', '0.0.0.0/0', '10.68.09.0/24'])
def test_untrusted_prefix_never_prints_partial_vty_commands(tmp_path, desired):
    result, _, _ = run(tmp_path, [node('r640', [])], desired=desired)
    assert result.returncode != 0
    assert result.stdout == ''


def test_missing_accepted_ownership_is_not_authoritative_empty(tmp_path):
    result, _, _ = run(tmp_path, [node('r640', [])], desired='', program='unset owned_pod_cidrs\n' + PROGRAM)
    assert result.returncode != 0
    assert result.stdout == ''


def test_allocation_reordering_keeps_the_exact_export_configuration(tmp_path):
    first_dir = tmp_path / 'first'
    second_dir = tmp_path / 'second'
    first_dir.mkdir()
    second_dir.mkdir()
    first, _, _ = run(first_dir, [node('r640', ['10.68.9.0/24', '10.68.22.0/24'])])
    second, _, _ = run(second_dir, [node('r640', ['10.68.22.0/24', '10.68.9.0/24'])],
                       desired='10.68.22.0/24\n10.42.6.0/24\n10.68.9.0/24')
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout


def test_same_kubernetes_node_accepts_cilium_object_rollover(tmp_path):
    result, state, _ = run(tmp_path, [node('r640', ['10.68.9.0/24'], uid='new-cilium-uid')],
                           previous(['10.68.22.0/24'], uid='old-cilium-uid'),
                           desired='10.42.6.0/24\n10.68.9.0/24')
    assert result.returncode == 0, result.stderr
    assert set(permits(result.stdout)) == {'10.42.6.0/24', '10.68.9.0/24', VIP}
    assert state['sourceUID'] == 'new-cilium-uid'


def test_unreviewed_vip_never_renders_partial_boundary_commands(tmp_path):
    program = PROGRAM.replace('10.251.0.4/32', '0.0.0.0/0')
    result, _, _ = run(tmp_path, [node('r640', [])], program=program)
    assert result.returncode != 0 and result.stdout == ''
