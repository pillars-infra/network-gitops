#!/usr/bin/env python3
"""Use the same signed executor validation without changing accepted state."""
import argparse
import json
from pathlib import Path
import yaml
from ssa_executor import Executor, Store, Rejected, PROTECTED_KINDS
from unified_bundle import object_identity

def preflight(executor,contract,operation,bundle,state_dir):
    _,objects,_=executor.validate(contract,operation,bundle,Store(state_dir,operation['releaseId']))
    executor.verify_signature(operation)
    requested=set(operation.get('forceConflictObjects',[]))
    allowed=set(contract['spec']['authorization'].get('forceConflictObjects',[]))
    if requested and operation['action']!='force-reconcile' or not requested.issubset(allowed):
        raise Rejected('unauthorized force-conflict objects')
    if any(o['kind'] in PROTECTED_KINDS and object_identity(o) in requested for o in objects):
        raise Rejected('protected objects cannot use force-conflicts')
    audited=executor.with_audit(objects,operation)
    if contract["spec"]["authorization"].get("requireExisting",False):audited=executor.with_existing_versions(audited)
    executor.apply(audited,contract['spec']['authorization']['fieldManager'],dry_run=True,force_objects=requested)
    return {'releaseId':operation['releaseId'],'preflight':'accepted','inventory':[object_identity(o) for o in objects]}

def main():
    p=argparse.ArgumentParser();p.add_argument('--contract',type=Path,required=True);p.add_argument('--operation',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--state-dir',type=Path,required=True);a=p.parse_args()
    result=preflight(Executor(),yaml.safe_load(a.contract.read_text()),json.loads(a.operation.read_text()),a.bundle,a.state_dir)
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__':main()
