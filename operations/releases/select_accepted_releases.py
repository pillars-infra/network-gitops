#!/usr/bin/env python3
"""Select accepted releases using only exact state ConfigMap GETs.

This snapshot reduces empty jobs; execution must re-read and authorize its state.
"""
import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import tempfile
import time
import jsonschema
from unified_bundle import validate_schema

from kube_transport import transient_failure
from operation_materialize import accepted_bundle, state_configmap_name
from profile import ROOT, replay_matrix


def read_state(argv, runner, sleeper):
    for attempt in range(3):
        try:
            result=runner(argv,capture_output=True,text=True,timeout=10)
        except subprocess.TimeoutExpired:
            if attempt == 2:raise
        else:
            if not result.returncode or not transient_failure(result.stdout,result.stderr) or attempt == 2:
                return result
        sleeper(2 ** attempt)
    raise AssertionError('bounded state read exhausted without a result')


def select(matrix, root=ROOT, runner=subprocess.run, sleeper=time.sleep):
    selected, skipped, invalid = [], [], []
    with tempfile.TemporaryDirectory(prefix='accepted-selector-') as directory:
        def inspect(entry):
            release=entry['release-id']
            path=Path(directory)/(release+'.json')
            try:
                result=read_state(['kubectl','get','configmap',state_configmap_name(release),'--namespace',entry['namespace'],
                                  '--ignore-not-found','-o','json'],runner,sleeper)
                if result.returncode:
                    return 'invalid',release,'state-read-failed',entry
                if not result.stdout.strip():
                    return 'skipped',release,'no-accepted-state',entry
                cm=json.loads(result.stdout)
                if not isinstance(cm,dict):raise ValueError('invalid state envelope')
                raw=cm.get('data',{}).get('accepted-state.json')
                if not raw:
                    return 'skipped',release,'no-accepted-state',entry
                state=json.loads(raw)
                validate_schema(state,"release-accepted-state.schema.json")
                if state.get('blocked') or state.get('suspended'):
                    return 'skipped',release,'blocked-or-suspended',entry
                accepted=state.get('acceptedDigest',state.get('acceptedDigest',state.get('healthyDigest')))
                if not accepted or accepted!=state.get('appliedDigest'):
                    return 'skipped',release,'not-accepted',entry
                path.write_text(json.dumps(cm))
                accepted_bundle(path,root/entry['contract'])
                return 'selected',release,'',entry
            except subprocess.TimeoutExpired:
                return 'invalid',release,'state-read-timeout',entry
            except (ValueError,KeyError,TypeError,jsonschema.ValidationError):
                return 'invalid',release,'invalid-or-changed-acceptance',entry
        # Exact GETs remain independently authorized, but a broken public edge must
        # not multiply one transport timeout by every contract in the domain.
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4,max(1,len(matrix)))) as pool:
            results=list(pool.map(inspect,matrix))
        for kind,release,reason,entry in results:
            if kind=='selected':selected.append(entry)
            elif kind=='skipped':skipped.append((release,reason))
            else:invalid.append((release,reason))
    return selected,skipped,invalid


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--github-output',type=Path,required=True)
    parser.add_argument('--summary',type=Path,required=True)
    args=parser.parse_args()
    selected,skipped,invalid=select(replay_matrix())
    with args.github_output.open('a') as output:
        output.write('matrix='+json.dumps({'include':selected},separators=(',',':'))+'\n')
        output.write('has-accepted='+('true' if selected else 'false')+'\n')
        output.write(f'invalid={len(invalid)}\n')
    with args.summary.open('a') as summary:
        summary.write(f'Accepted network selection: {len(selected)} eligible, {len(skipped)} skipped, {len(invalid)} invalid.\n\n')
        for release,reason in skipped+invalid:
            summary.write(f'- `{release}`: {reason}\n')
    for release,reason in invalid:
        print(f'::warning title=Network acceptance selection::{release}: {reason}')


if __name__=='__main__':
    main()
