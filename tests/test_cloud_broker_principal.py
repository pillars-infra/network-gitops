"""The broker ingress migration selects the actual Cloud workload, not its namespace."""
from pathlib import Path
import yaml

ROOT = Path(__file__).parents[1]


def policies():
    return {o['kind']: o for o in yaml.safe_load_all(
        (ROOT / 'clusters/re8ch/among-clusters-cloud-broker-access.yaml').read_text())
        if o['kind'] in {'NetworkPolicy', 'CiliumNetworkPolicy'}}


def test_kubernetes_policy_only_allows_current_cloud_workload():
    policy = policies()['NetworkPolicy']['spec']
    assert policy['podSelector']['matchLabels'] == {
        'app.kubernetes.io/name': 'among-clusters-credential-broker'}
    assert policy['policyTypes'] == ['Ingress']
    rule, = policy['ingress']
    assert rule['ports'] == [{'port': 8080, 'protocol': 'TCP'}]
    peer, = rule['from']
    def allowed(namespace, app):
        return all({'kubernetes.io/metadata.name': namespace}.get(k) == v
                   for k, v in peer['namespaceSelector']['matchLabels'].items()) and all(
                       {'app': app}.get(k) == v for k, v in peer['podSelector']['matchLabels'].items())
    assert allowed('ai-operations', 're8ch-cloud-platform')
    for namespace, app in [('ai-operations', 'cloud-platform-tool'),
                           ('ai-operations', 'other-workload'),
                           ('tenant-infrastructure', 'tenant-api'),
                           ('other-namespace', 're8ch-cloud-platform')]:
        assert not allowed(namespace, app)


def test_cilium_policy_has_same_exact_source_and_destination_scope():
    policy = policies()['CiliumNetworkPolicy']['spec']
    assert policy['endpointSelector']['matchLabels'] == {
        'app.kubernetes.io/name': 'among-clusters-credential-broker'}
    rule, = policy['ingress']
    peer, = rule['fromEndpoints']
    assert peer == {'matchLabels': {
        'k8s:app': 're8ch-cloud-platform',
        'k8s:io.kubernetes.pod.namespace': 'ai-operations'}}
    assert rule['toPorts'] == [{'ports': [{'port': '8080', 'protocol': 'TCP'}]}]
    assert set(rule) == {'fromEndpoints', 'toPorts'}
    assert set(policy) == {'endpointSelector', 'ingress'}


def test_existing_policy_names_and_exact_native_projection_are_retained():
    source = policies()
    rendered = {o['kind']: o for o in yaml.safe_load_all((ROOT /
        'releases/networking-native-credential-broker/resources.yaml').read_text())
        if o['metadata']['name'] == 'among-clusters-broker-tool-access'}
    assert rendered == source
    assert all(o['metadata'] == {'name': 'among-clusters-broker-tool-access',
        'namespace': 'credential-broker'} for o in source.values())


def test_platform_bootstrap_binds_only_existing_grant_to_actual_cloud_sa():
    objects = {o['kind']: o for o in yaml.safe_load_all((ROOT /
        'clusters/re8ch/among-clusters-cloud-broker-access.yaml').read_text())
        if o['metadata']['namespace']=='byoc-pilot'}
    role, binding = objects['Role'], objects['RoleBinding']
    assert role['metadata']['namespace'] == binding['metadata']['namespace'] == 'byoc-pilot'
    assert role['rules'] == [{'apiGroups': ['peering.re8ch.com'],
        'resources': ['managedaccessgrants'],
        'resourceNames': ['re8ch-atlantic-headlamp-admin'], 'verbs': ['get', 'use']},
        {'apiGroups': ['peering.re8ch.com'], 'resources': ['serviceadvertisements'],
         'resourceNames': ['re8ch-atlantic-default-kubernetes'], 'verbs': ['get']},
        {'apiGroups': ['peering.re8ch.com'], 'resources': ['importedservices'],
         'resourceNames': ['re8ch-atlantic-default-kubernetes-re8ch-atlantic'], 'verbs': ['get']},
        {'apiGroups': ['peering.re8ch.com'], 'resources': ['peers'],
         'resourceNames': ['re8ch-atlantic'], 'verbs': ['get']},
        {'apiGroups':['peering.re8ch.com'], 'resources':['clusteridentities'],
         'resourceNames':['re8ch'], 'verbs':['get']}]
    assert binding['subjects'] == [{'kind': 'ServiceAccount',
        'name': 're8ch-cloud-platform', 'namespace': 'ai-operations'}]
    assert binding['roleRef'] == {'apiGroup': 'rbac.authorization.k8s.io',
        'kind': 'Role', 'name': role['metadata']['name']}
    assert role['metadata']['annotations']['peering.re8ch.com/reviewed-grant-uid'] == (
        'd9fae24e-cea9-4014-8c93-0837bd8e7e60')
    ledger = __import__('json').loads((ROOT / 'operations/releases/native-authority.json').read_text())
    bootstrap = ledger['platformBootstrap']
    assert role in bootstrap and binding in bootstrap


def test_self_api_metadata_is_exact_namespace_and_name_only():
    objects={o['kind']:o for o in yaml.safe_load_all((ROOT /
        'clusters/re8ch/among-clusters-cloud-broker-access.yaml').read_text())
        if o['metadata']['namespace']=='default'}
    role,binding=objects['Role'],objects['RoleBinding']
    assert role['rules']==[{'apiGroups':[''], 'resources':['services'],
        'resourceNames':['kubernetes'], 'verbs':['get']}]
    assert binding['subjects']==[{'kind':'ServiceAccount',
        'namespace':'ai-operations','name':'re8ch-cloud-platform'}]
    assert binding['roleRef']['name']==role['metadata']['name']
    ledger=__import__('json').loads((ROOT/'operations/releases/native-authority.json').read_text())
    assert role in ledger['platformBootstrap'] and binding in ledger['platformBootstrap']
