from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]

def test_durable_state_write_refreshes_expired_outer_identity(tmp_path):
    import os
    import subprocess
    for workflow, job in [('static-release.yml', 'execute'), ('networking-reconcile.yml', 'reconcile')]:
        definition = yaml.safe_load((ROOT / '.github/workflows' / workflow).read_text())
        script = next(step['run'] for step in definition['jobs'][job]['steps'] if 'state-patch --configmap' in step.get('run', ''))
        script = script[script.index('if [[ -s "$RUNNER_TEMP/state-patch.json"'):]
        run_dir = tmp_path / job
        run_dir.mkdir()
        (run_dir / 'state-patch.json').write_text('{}')
        (run_dir / 'result.json').write_text('{"outcome":"healthy","health":{"status":"healthy"}}')
        bins = run_dir / 'bin'
        bins.mkdir()
        curl = bins / 'curl'
        curl.write_text('#!/bin/sh\n[ "$REFRESH_FAIL" = no ] || exit 22\nprintf \'{"value":"fresh-fixture-token"}\'\n')
        curl.chmod(0o755)
        kubectl = bins / 'kubectl'
        kubectl.write_text('''#!/bin/sh
case "$1 $2" in
  'config set-credentials')
    [ "$3" = release-executor ] && [ "$4" = --token=fresh-fixture-token ] || exit 31
    touch "$RUNNER_TEMP/refreshed" ;;
  'patch configmap')
    [ -f "$RUNNER_TEMP/refreshed" ] || exit 32
    touch "$RUNNER_TEMP/patched" ;;
  *) exit 33 ;;
esac
''')
        kubectl.chmod(0o755)
        env = {**os.environ, 'PATH': str(bins) + os.pathsep + os.environ['PATH'], 'RUNNER_TEMP': str(run_dir),
               'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'fixture', 'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://fixture.invalid',
               'EXECUTOR_AUDIENCE': 'https://kube-api.re8ch.com/release-executor-test', 'REFRESH_FAIL': 'no',
               'state_name': 'ssa-state-demo', 'TARGET_NAMESPACE': 'ops', 'executor_status': '0'}
        subprocess.run(['bash', '-euo', 'pipefail', '-c', script], env=env, check=True, capture_output=True)
        assert (run_dir / 'patched').exists()
        (run_dir / 'patched').unlink()
        (run_dir / 'refreshed').unlink()
        env['REFRESH_FAIL'] = 'yes'
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], env=env, capture_output=True)
        assert result.returncode != 0
        assert not (run_dir / 'patched').exists()
