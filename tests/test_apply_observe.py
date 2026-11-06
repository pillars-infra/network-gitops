import json
import shutil
import pytest
import test_ssa_release_executor as base
import observe_runtime


def test_apply_only_does_not_consult_unhealthy_runtime(tmp_path):
    contract, operation, bundle = base.prepare(tmp_path)
    runner = base.Runner(live={'metadata': {'generation': 2}, 'spec': {'replicas': 1}, 'status': {'observedGeneration': 2, 'availableReplicas': 0}})
    ex = base.executor.Executor(runner=runner, now=lambda: base.NOW)
    ex.apply_only = True
    ex.wait_healthy = lambda *args: pytest.fail('SSA must not call Observe')
    result = ex.reconcile(contract, operation, bundle, tmp_path/'state', verify_signature=False)
    assert result['outcome'] == 'applied'
    assert result['health']['status'] == 'unknown'
    state = base.executor.Store(tmp_path/'state', operation['releaseId']).state()
    assert state['acceptedDigest'] == operation['bundle']['digest']
    assert 'healthyDigest' not in state
    assert not state['blocked']


def test_apply_only_still_rejects_ssa_conflicts(tmp_path):
    contract, operation, bundle = base.prepare(tmp_path)
    ex = base.executor.Executor(runner=base.Runner(conflict=True), now=lambda: base.NOW)
    ex.apply_only = True
    with pytest.raises(base.executor.Rejected):
        ex.reconcile(contract, operation, bundle, tmp_path/'state', verify_signature=False)


@pytest.mark.parametrize('health', ['healthy', 'degraded', 'unknown'])
def test_observation_never_changes_ssa_outcome_or_state(tmp_path, monkeypatch, health):
    contract, operation, bundle = base.prepare(tmp_path)
    (tmp_path/'operation.json').write_text(json.dumps(operation))
    (tmp_path/'pulled').mkdir()
    shutil.copyfile(bundle, tmp_path/'pulled/release.bundle')
    (tmp_path/'result.json').write_text(json.dumps({'releaseId': operation['releaseId'], 'outcome': 'applied'}))
    class Observer:
        def wait_healthy(self, *args):
            if health == 'unknown': raise RuntimeError('unavailable API; never expose raw payload')
            return health == 'healthy', 'observed runtime'
    monkeypatch.setattr(observe_runtime, 'Executor', Observer)
    observe_runtime.observe(tmp_path, contract=contract)
    result = json.loads((tmp_path/'result.json').read_text())
    assert result['outcome'] == 'applied'
    assert result['health']['status'] == health
    assert not (tmp_path/'state').exists()
