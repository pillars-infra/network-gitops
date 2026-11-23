"""Execute the shipped shell helper with real jq and isolated fake FRR metadata."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def source():
    return next(d for d in yaml.safe_load_all((ROOT/'clusters/re8ch/resources.yaml').read_text())
                if d and d.get('kind') == 'ConfigMap' and d['metadata']['name'] == 'podcidr-fabric-reconciler')


def node(name='local', cidrs=None, *, missing=False, uid='node-uid'):
    item = {'metadata': {'name': name, 'uid': uid, 'resourceVersion': '123', 'ownerReferences': [{'apiVersion': 'v1', 'kind': 'Node', 'name': name, 'uid': 'kube-node-uid'}]},
            'spec': {'ipam': {'pools': {}}}}
    if not missing:
        item['spec']['ipam']['pools']['allocated'] = [{'pool': 'apps', 'cidrs': cidrs or []}]
    return item


def ledger(prefixes, uid='node-uid'):
    return {'version': 1, 'nodeName': 'local', 'sourceUID': uid, 'sourceResourceVersion': '99', 'ownerNodeUID': 'kube-node-uid', 'prefixes': prefixes}


def run_helper(tmp_path, nodes, previous=None, desired='10.42.1.0/24\n10.68.1.0/24',
               static=None, bgp=None, program=None):
    helper = tmp_path/'helper.sh'
    helper.write_text(source()['data']['owned-prefixes.sh'])
    inventory = tmp_path/'inventory.json'
    inventory.write_text(json.dumps({'nodes': [{'name': 'local'}, {'name': 'other'}], 'routeServers': []}))
    helper.write_text(helper.read_text().replace('/config/inventory.json', str(inventory)))
    snapshot = tmp_path/'snapshot.json'
    snapshot.write_text(json.dumps({'items': nodes}))
    state = tmp_path/'state'/'owned.json'
    if previous is not None:
        state.parent.mkdir()
        state.write_text(json.dumps(previous))
    (tmp_path/'static.json').write_text(json.dumps(static or {}))
    (tmp_path/'bgp.json').write_text(json.dumps(bgp or {}))
    calls = tmp_path/'calls'
    script = '''set -eu
. "$HELPER"
host() {
  printf '%s\\n' "$*" >> "$CALLS"
  case "$*" in
    *'show ip route '*) cat "$STATIC" ;;
    *'show bgp ipv4 unicast '*) cat "$BGP" ;;
    *) return 1 ;;
  esac
}
prepare_owned_prefix_reconciliation
'''
    script += program or '''
retired_prefix_routes
retired_prefix_networks
commit_owned_prefix_reconciliation
'''
    env = {**os.environ, 'HELPER': str(helper), 'NODE_NAME': 'local', 'cilium_nodes': str(snapshot),
           'owned_prefix_ledger': str(state), 'owned_pod_cidrs': desired,
           'STATIC': str(tmp_path/'static.json'), 'BGP': str(tmp_path/'bgp.json'), 'CALLS': str(calls)}
    result = subprocess.run(['sh', '-c', script], env=env, text=True, capture_output=True)
    return result, json.loads(state.read_text()) if state.exists() else None, calls.read_text() if calls.exists() else ''


def blackhole(prefix, *, distance=254):
    return {prefix: [{'protocol': 'static', 'distance': distance, 'nexthops': [{'blackhole': True}]}]}


def test_multiple_allocations_are_kept_and_only_previous_owned_are_withdrawn(tmp_path):
    result, state, calls = run_helper(tmp_path, [node(cidrs=['10.68.1.0/24', '10.68.22.0/24'])],
                                    ledger(['10.42.1.0/24', '10.68.12.0/24']),
                                    desired='10.42.1.0/24\n10.68.1.0/24\n10.68.22.0/24')
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['no ip route 10.68.12.0/24 Null0 254', 'no network 10.68.12.0/24']
    assert state == ledger(['10.42.1.0/24', '10.68.1.0/24', '10.68.22.0/24']) | {'sourceResourceVersion': '123'}
    assert calls == ''


@pytest.mark.parametrize('snapshot', [[], [node(missing=True)], [node(cidrs=['10.68.1.0/24']), node('other', ['10.68.1.0/24'])]])
def test_unknown_or_conflicting_allocations_do_not_withdraw_or_replace_ledger(tmp_path, snapshot):
    previous = ledger(['10.42.1.0/24', '10.68.12.0/24'])
    result, state, _ = run_helper(tmp_path, snapshot, previous)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''
    assert state == previous


def test_authoritative_empty_allocations_withdraw_previous_multi_pool_prefixes(tmp_path):
    result, state, _ = run_helper(tmp_path, [node(cidrs=[])],
                                  ledger(['10.42.1.0/24', '10.68.1.0/24', '10.68.22.0/24']), desired='10.42.1.0/24')
    assert result.returncode == 0, result.stderr
    assert 'no network 10.68.1.0/24' in result.stdout and 'no network 10.68.22.0/24' in result.stdout
    assert state['prefixes'] == ['10.42.1.0/24']


def test_bootstrap_only_reassigned_exact_local_origin_and_null0_pair(tmp_path):
    prefix = '10.68.12.0/24'
    result, state, calls = run_helper(tmp_path, [node(cidrs=['10.68.1.0/24']), node('other', [prefix])],
                                    static=blackhole(prefix), bgp={'paths': [{'local': True, 'sourced': True}]})
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f'no ip route {prefix} Null0 254', f'no network {prefix}']
    assert f'show ip route {prefix} json' in calls and f'show bgp ipv4 unicast {prefix} json' in calls


@pytest.mark.parametrize('other,route,bgp', [
    ('unknown', blackhole('10.68.12.0/24'), {'paths': [{'local': True, 'sourced': True}]}),
    ('other', blackhole('10.68.12.0/24', distance=10), {'paths': [{'local': True, 'sourced': True}]}),
    ('other', blackhole('10.68.12.0/24'), {'paths': [{'valid': True}]}),
    ('other', {}, {'paths': [{'local': True, 'sourced': True}]}),
])
def test_unowned_provider_static_or_learned_routes_are_not_withdrawn(tmp_path, other, route, bgp):
    result, _, _ = run_helper(tmp_path, [node(cidrs=['10.68.1.0/24']), node(other, ['10.68.12.0/24'])], static=route, bgp=bgp)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ''


@pytest.mark.parametrize('previous', [ledger(['10.68.1.0/24']) | {'ownerNodeUID': 'replaced-node'}, {'version': 1},
                                      ledger(['10.68.1.0/24; echo unsafe'])])
def test_replaced_node_uid_or_corrupt_ledger_fails_before_frr(tmp_path, previous):
    result, state, calls = run_helper(tmp_path, [node(cidrs=['10.68.1.0/24'])], previous)
    assert result.returncode != 0
    assert calls == '' and state == previous


def test_failed_frr_batch_keeps_previous_durable_ownership(tmp_path):
    previous = ledger(['10.68.12.0/24'])
    result, state, _ = run_helper(tmp_path, [node(cidrs=['10.68.1.0/24'])], previous,
                                  program='false\ncommit_owned_prefix_reconciliation\n')
    assert result.returncode != 0 and state == previous


def test_successful_replay_has_no_retired_prefixes_and_empty_ledger_is_valid(tmp_path):
    result, state, _ = run_helper(tmp_path, [node(cidrs=[])], ledger([]), desired='')
    assert result.returncode == 0, result.stderr
    assert result.stdout == '' and state['prefixes'] == []


def test_every_fabric_peer_map_rewrites_admitted_transit_to_peer_reachable_address(tmp_path):
    result, _, _ = run_helper(tmp_path, [node(cidrs=[])], program='''
fabric_route_server_next_hop_maps 192.0.2.1 192.0.2.2 192.0.2.3
fabric_peer_next_hop 192.0.2.4
''')
    assert result.returncode == 0, result.stderr
    for mode, address in [('IDENTITY', '192.0.2.1'), ('TRANSPORT', '192.0.2.2'), ('INTERCONNECT', '192.0.2.3')]:
        assert f'route-map POD-FABRIC-RR-{mode}-OUT permit 10\nmatch ip address prefix-list POD-FABRIC-OUT\nset ip next-hop {address}' in result.stdout
        assert f'no route-map POD-FABRIC-RR-{mode}-OUT permit 20' in result.stdout
    assert result.stdout.endswith('no neighbor 192.0.2.4 attribute-unchanged next-hop\nneighbor 192.0.2.4 next-hop-self force\n')


def test_authenticated_helper_mount_and_configuration_before_workload_stages():
    cm = source()
    helper = cm['data']['owned-prefixes.sh']
    assert cm['data']['reconcile.sh'].startswith('ENC[')
    assert cm['metadata']['annotations']['networking.re8ch.com/owned-prefix-helper-sha256'] == hashlib.sha256(helper.encode()).hexdigest()
    subprocess.run(['sh', '-n'], input=helper, text=True, check=True)
    ds = next(d for d in yaml.safe_load_all((ROOT/'clusters/re8ch/resources.yaml').read_text())
              if d and d.get('kind') == 'DaemonSet' and d['metadata']['name'] == cm['metadata']['name'])
    items = next(v for v in ds['spec']['template']['spec']['volumes'] if v['name'] == 'config')['projected']['sources'][0]['configMap']['items']
    assert {'key': 'owned-prefixes.sh', 'path': 'owned-prefixes.sh'} in items
    assert len(ds['spec']['template']['metadata']['annotations']['networking.re8ch.com/reconciler-sha256']) == 64
    contract = yaml.safe_load((ROOT/'contracts/networking-native-kube-system.yaml').read_text())
    assert contract['spec']['lifecycle']['stages'][0] == {'name': 'configuration', 'kinds': ['ConfigMap']}
    assert 'DaemonSet' in contract['spec']['lifecycle']['stages'][1]['kinds']


def test_cilium_object_rollover_on_same_kubernetes_node_migrates_ledger_and_reclaims(tmp_path):
    result, state, _ = run_helper(tmp_path, [node(cidrs=['10.68.1.0/24'], uid='new-cilium-uid')],
                                  ledger(['10.68.12.0/24'], uid='old-cilium-uid'))
    assert result.returncode == 0, result.stderr
    assert 'no network 10.68.12.0/24' in result.stdout
    assert state['sourceUID'] == 'new-cilium-uid' and state['ownerNodeUID'] == 'kube-node-uid'


def test_missing_owner_reference_is_unknown_not_authoritative_empty(tmp_path):
    observed = node(cidrs=[])
    observed['metadata'].pop('ownerReferences')
    previous = ledger(['10.68.12.0/24'])
    result, state, _ = run_helper(tmp_path, [observed], previous, desired='')
    assert result.returncode == 0, result.stderr
    assert result.stdout == '' and state == previous
