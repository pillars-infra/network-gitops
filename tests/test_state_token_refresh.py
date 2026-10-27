from pathlib import Path
import yaml
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"operations/releases"))
ROOT=Path(__file__).resolve().parents[1]

def test_durable_state_write_refreshes_expired_outer_identity(tmp_path):
    import os
    import subprocess
    for workflow, job in [('static-release.yml', 'execute'), ('networking-reconcile.yml', 'reconcile')]:
        definition = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())
        script = next(step['run'] for step in definition['jobs'][job]['steps'] if 'state-patch --configmap' in step.get('run', ''))
        script = script[script.index('if [[ -s "$RUNNER_TEMP/state-patch.json"'):]
        assert '--token=' not in script and 'Authorization: bearer' not in script
        run_dir = tmp_path / job
        run_dir.mkdir()
        (run_dir / 'state-patch.json').write_text('{}')
        (run_dir / 'result.json').write_text('{"outcome":"healthy","health":{"status":"healthy"}}')
        bins = run_dir / 'bin'
        bins.mkdir()
        for name, body in {
            'python': '[ "$1" = operations/releases/refresh_kubeconfig.py ] && [ "$REFRESH_FAIL" = no ] || exit 22\ntouch "$RUNNER_TEMP/refreshed"',
            'kubectl': '[ "$1 $2" = "patch configmap" ] && [ -f "$RUNNER_TEMP/refreshed" ] || exit 32\ntouch "$RUNNER_TEMP/patched"',
        }.items():
            path = bins / name
            path.write_text('#!/bin/sh\n' + body + '\n')
            path.chmod(0o755)
        env = {**os.environ, 'PATH': str(bins) + os.pathsep + os.environ['PATH'], 'RUNNER_TEMP': str(run_dir),
               'REFRESH_FAIL': 'no', 'state_name': 'ssa-state-demo', 'TARGET_NAMESPACE': 'ops', 'executor_status': '0'}
        subprocess.run(['bash', '-euo', 'pipefail', '-c', script], env=env, cwd=run_dir, check=True, capture_output=True)
        assert (run_dir / 'patched').exists()
        (run_dir / 'patched').unlink()
        (run_dir / 'refreshed').unlink()
        env['REFRESH_FAIL'] = 'yes'
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], env=env, cwd=run_dir, capture_output=True)
        assert result.returncode != 0
        assert not (run_dir / 'patched').exists()


def test_refresh_uses_existing_oidc_guards_and_atomic_private_kubeconfig(tmp_path, monkeypatch, capsys):
    import refresh_kubeconfig as refresh
    import pytest
    path = tmp_path / 'kubeconfig'
    original = {'users': [{'name': 'release-executor', 'user': {'token': 'old'}},
                          {'name': 'other', 'user': {'token': 'unchanged'}}],
                'current-context': 'release-executor', 'clusters': [{'name': 'cluster'}]}
    path.write_text(yaml.safe_dump(original))
    monkeypatch.setenv('KUBECONFIG', str(path))
    monkeypatch.setattr(refresh.Executor, 'actions_kube_token', lambda self: 'fresh-fixture-token')
    refresh.refresh()
    updated = yaml.safe_load(path.read_text())
    assert updated['users'][0]['user'] == {'token': 'fresh-fixture-token'}
    assert updated['users'][1:] == original['users'][1:]
    assert updated['clusters'] == original['clusters']
    assert path.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr() == ('', '')
    before = path.read_bytes()
    monkeypatch.setattr(refresh.Executor, 'actions_kube_token', lambda self: None)
    with pytest.raises(refresh.Rejected):
        refresh.refresh()
    assert path.read_bytes() == before
