import json
from pathlib import Path
import yaml
from test_ssa_release_executor import executor, NOW, Runner, staged_release, operation_for
from unified_bundle import compile_bundle

ROOT = Path(__file__).resolve().parents[1]


def test_actual_af_contract_orders_configuration_before_workloads():
    contract = yaml.safe_load((ROOT/'contracts/networking-helm-advanced-fabric-kube-system.yaml').read_text())
    inventory = json.loads((ROOT/'operations/releases/advanced-fabric-authority.json').read_text())['inventory']
    # Structural compilation against the exact approved inventory; no private data.
    objects = []
    for identity in inventory:
        group, kind, namespace, name = identity.split('/')
        item = {'apiVersion': 'v1' if group == 'core' else group+'/v1', 'kind': kind, 'metadata': {'name': name}}
        if namespace != '_': item['metadata']['namespace'] = namespace
        objects.append(item)
    _, manifest = compile_bundle(contract, yaml.safe_dump_all(objects).encode())
    positions = {identity: index for index, stage in enumerate(manifest['stages']) for identity in stage['inventory']}
    config = positions['core/ConfigMap/kube-system/advanced-fabric-runtime']
    fabric = positions['networking.advfab.org/AdvancedFabric/_/advanced-fabric']
    for identity in inventory:
        if identity.startswith(('apps/DaemonSet/', 'apps/Deployment/')):
            assert config < fabric < positions[identity]


def test_rollback_uses_current_configuration_before_workload_order(tmp_path):
    value, archive, manifest, path = staged_release(tmp_path, 'previous', 'old', 'old-code')
    value['spec']['lifecycle']['stages'] = [
        {'name': 'configuration', 'kinds': ['ConfigMap']}, {'name': 'runtime', 'kinds': ['Deployment']}]
    operation = operation_for(value, archive, manifest, 2)
    _, objects = executor.load_archive(path)
    previous = {'appliedDigest': operation['bundle']['digest'], 'payloadDigest': operation['bundle']['payloadDigest'],
                'bundleReference': operation['bundle']['reference'], 'inventory': manifest['inventory'],
                'objectRefs': [executor.object_ref(item) for item in objects]}
    store = executor.Store(tmp_path/'state', 'demo')
    store.cache_bundle(path, previous['appliedDigest'])
    runner = Runner()
    executor.Executor(runner=runner, now=lambda: NOW).rollback(
        previous, manifest, objects, value, operation, 're8ch-release/demo', store, 'forward failure')
    kinds = [json.loads(data)['kind'] for argv, data in runner.calls if argv[:2] == ['kubectl', 'apply']]
    assert kinds == ['ConfigMap', 'Deployment', 'ConfigMap', 'Deployment']
