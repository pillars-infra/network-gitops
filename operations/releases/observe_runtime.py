"""Read-only health observation, independent of the SSA execution result."""
import datetime as dt
import json
import os
from pathlib import Path

import yaml
from ssa_executor import Executor, load_archive
from unified_bundle import canonical, digest


def observe(root, contract=None):
    operation_path = root / 'operation.json'
    bundle = root / 'pulled/release.bundle'
    if not operation_path.exists() or not bundle.exists():
        return None
    operation = json.loads(operation_path.read_text())
    observation = {'releaseId': operation['releaseId'], 'digest': operation['bundle']['digest'],
                   'observedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'health': {'status': 'unknown', 'reason': 'Runtime observation unavailable'}}
    try:
        if digest(bundle.read_bytes()) != operation['bundle']['payloadDigest']:
            raise ValueError('bundle mismatch')
        _, objects = load_archive(bundle)
        contracts = Path(__file__).resolve().parents[2] / 'contracts'
        contract = contract or next(v for p in contracts.rglob('*.yaml')
                        if isinstance(v := yaml.safe_load(p.read_text()), dict)
                        and v.get('metadata', {}).get('name') == operation['releaseId']
                        and digest(canonical(v)) == operation['contractDigest'])
        if os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL'):
            os.environ.setdefault('EXECUTOR_AUDIENCE', operation['github']['audience'])
        healthy, reason = Executor().wait_healthy(objects, 0, contract['spec']['lifecycle'].get('healthChecks'))
        observation['health'] = {'status': 'healthy' if healthy else 'degraded', 'reason': reason}
    except Exception as error:
        # Never expose command input, decrypted values or raw API error bodies.
        observation['health'] = {'status': 'unknown', 'reason': 'Runtime observation unavailable (' + type(error).__name__ + ')'}
    (root / 'observation.json').write_text(json.dumps(observation, sort_keys=True) + '\n')
    for path in (root / 'result.json', Path('static-release-result.json')):
        if path.exists() and path.stat().st_size:
            result = json.loads(path.read_text())
            if (result.get('releaseId', result.get('release')) == operation['releaseId']
                    and result.get('outcome') in {'applied', 'healthy', 'degraded', 'aligned', 'recovered'}):
                result['health'] = observation['health']
                path.write_text(json.dumps(result, sort_keys=True) + '\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as stream:
            stream.write('\nObserve: ' + operation['releaseId'] + ' · ' + observation['health']['status'] + '\n\n' + observation['health']['reason'] + '\n')
    if observation['health']['status'] != 'healthy':
        print('::warning::Runtime observation is ' + observation['health']['status'] + '; SSA execution status is independent. See observation artifact.')
    return observation


if __name__ == '__main__':
    observe(Path(os.environ['RUNNER_TEMP']))
