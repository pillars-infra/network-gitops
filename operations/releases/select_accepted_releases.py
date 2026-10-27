#!/usr/bin/env python3
"""Select healthy accepted releases using only exact state ConfigMap GETs.

This snapshot reduces empty jobs; execution must re-read and authorize its state.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import jsonschema
from unified_bundle import validate_schema

from operation_materialize import accepted_bundle, state_configmap_name
from profile import ROOT, replay_matrix


def select(matrix, root=ROOT, runner=subprocess.run):
    selected, skipped, invalid = [], [], []
    with tempfile.TemporaryDirectory(prefix='accepted-selector-') as directory:
        path=Path(directory)/'state.json'
        for entry in matrix:
            release=entry['release-id']
            try:
                result=runner(['kubectl','get','configmap',state_configmap_name(release),'--namespace',entry['namespace'],
                               '--ignore-not-found','-o','json'],capture_output=True,text=True,timeout=10)
                if result.returncode:
                    invalid.append((release,'state-read-failed'));continue
                if not result.stdout.strip():
                    skipped.append((release,'no-accepted-state'));continue
                cm=json.loads(result.stdout)
                if not isinstance(cm,dict):raise ValueError('invalid state envelope')
                raw=cm.get('data',{}).get('accepted-state.json')
                if not raw:
                    skipped.append((release,'no-accepted-state'));continue
                state=json.loads(raw)
                validate_schema(state,"release-accepted-state.schema.json")
                if state.get('blocked') or state.get('suspended'):
                    skipped.append((release,'blocked-or-suspended'));continue
                if not state.get('healthyDigest') or state.get('healthyDigest')!=state.get('appliedDigest'):
                    skipped.append((release,'not-healthy-accepted'));continue
                path.write_text(json.dumps(cm))
                accepted_bundle(path,root/entry['contract'])
                selected.append(entry)
            except subprocess.TimeoutExpired:
                invalid.append((release,'state-read-timeout'))
            except (ValueError,KeyError,TypeError,jsonschema.ValidationError):
                invalid.append((release,'invalid-or-changed-acceptance'))
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
