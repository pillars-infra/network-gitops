import json
import os
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_release_job_failures_keep_separate_redacted_evidence(tmp_path):
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        if path.name == 'validate.yml':
            continue
        workflow = yaml.safe_load(path.read_text())
        for name, job in workflow['jobs'].items():
            if 'steps' not in job:
                continue
            step = next(s for s in job['steps'] if s.get('name') == 'Preserve workflow failure evidence')
            assert step['if'] == 'failure()'
            upload = next(s for s in job['steps'] if s.get('with', {}).get('name', '').startswith('workflow-failure-'))
            assert upload['if'] == 'failure()'
            assert '${{ github.run_attempt }}' in upload['with']['name']
            if 'matrix' in job.get('strategy', {}):
                assert '${{ strategy.job-index }}' in upload['with']['name']
            env = {**os.environ, 'RUNNER_TEMP': str(tmp_path), 'GITHUB_RUN_ID': '123', 'GITHUB_JOB': name,
                   'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'NEVER-LOG-THIS'}
            subprocess.run(['bash', '-euc', step['run']], env=env, check=True, capture_output=True)
            text = (tmp_path / 'workflow-failure.json').read_text()
            assert 'NEVER-LOG-THIS' not in text
            value = json.loads(text)
            assert value['outcome'] == 'failed' and value['health']['status'] == 'unknown'
            assert value['runId'] == '123' and value['job'] == name
            assert 'appliedDigest' not in value and 'healthyDigest' not in value
