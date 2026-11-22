"""Keep the L3 egress recovery local to the reviewed R640 node config."""
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_rendered_recovery_is_one_existing_node_config_not_a_cluster_wide_toggle():
    rendered = list(yaml.safe_load_all(subprocess.check_output(
        ['kubectl', 'kustomize', 'clusters/re8ch'], cwd=ROOT, text=True)))
    configs = [item for item in rendered if item and item.get('kind') == 'CiliumNodeConfig']
    recovery = [item for item in configs
                if item['spec'].get('defaults', {}).get('enable-host-legacy-routing') == 'true']
    assert len(recovery) == 1
    node = recovery[0]
    assert node['metadata']['name'] == 'r640-xdp-native'
    assert node['metadata']['namespace'] == 'kube-system'
    assert node['spec']['nodeSelector'] == {'matchLabels': {'kubernetes.io/hostname': 'r640'}}
    defaults = node['spec']['defaults']
    assert defaults['bpf-lb-acceleration'] == 'native'
    assert defaults['enable-bpf-masquerade'] == 'true'
    assert defaults['devices'] == defaults['direct-routing-device'] == 'eno2np1'
    assert 'mtu' not in defaults and not any('mss' in key for key in defaults)
    chart = yaml.safe_load((ROOT/'clusters/re8ch/cilium-release.yaml').read_text())
    assert chart['spec']['values']['bpf'].get('hostLegacyRouting', False) is False


def test_existing_native_contract_and_rendered_release_deliver_the_same_recovery():
    contract = yaml.safe_load((ROOT/'contracts/networking-native-kube-system.yaml').read_text())
    assert contract['spec']['authorization']['requireExisting'] is True
    assert 'cilium.io/CiliumNodeConfig' in contract['spec']['authorization']['resources']
    assert 'r640-xdp-native' in contract['spec']['authorization']['objectNames']
    release = list(yaml.safe_load_all(subprocess.check_output(
        ['kubectl', 'kustomize', contract['spec']['source']['path']], cwd=ROOT, text=True)))
    target = next(item for item in release if item.get('kind') == 'CiliumNodeConfig'
                  and item['metadata']['name'] == 'r640-xdp-native')
    desired = yaml.safe_load((ROOT/'clusters/re8ch/r640-cilium-datapath.yaml').read_text())
    assert target['spec'] == desired['spec']
    assert not any(item.get('kind') in {'Role', 'RoleBinding', 'ClusterRole', 'ClusterRoleBinding'}
                   for item in release)
