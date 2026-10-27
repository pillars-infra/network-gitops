#!/usr/bin/env python3
"""Check a certified build commit against the current flat release source."""
import argparse
from pathlib import Path
import re
import subprocess
import yaml

def verify(commit, contract_path, root=Path('.')):
    if not re.fullmatch(r'[0-9a-f]{40}',commit):raise ValueError('reuse requires an exact build commit SHA')
    path=Path(contract_path)
    if path.is_absolute() or '..' in path.parts:raise ValueError('contract path escapes repository')
    contract=yaml.safe_load((root/path).read_text())
    source=Path(contract['spec']['source']['path'])
    if source.is_absolute() or '..' in source.parts:raise ValueError('source path escapes repository')
    paths=[path,source]
    if contract['spec']['source'].get('protectedHelm')=='advanced-fabric':
        if str(path)!='contracts/networking-helm-advanced-fabric-kube-system.yaml' or str(source)!='releases/networking-helm-advanced-fabric-kube-system':raise ValueError('unknown protected release')
        paths=[path,Path('clusters/re8ch'),Path('charts'),Path('schemas')]
        paths += [Path('operations/releases')/name for name in ['helm-lock.json','advanced-fabric-inventory.json','compile_protected_helm.py','compile_helm.py','compile_native.py','restricted_configmap.py','restricted_object.py','unified_bundle.py','operation_materialize.py','profile.py']]
        boundary=(root/'clusters/re8ch').resolve()
        for file in boundary.rglob('kustomization.yaml'):
            value=yaml.safe_load(file.read_text())
            if set(value)-{'apiVersion','kind','resources','patches'}:raise ValueError('unsupported protected renderer dependency')
            refs=list(value.get('resources',[]))+[p['path'] for p in value.get('patches',[]) if 'path' in p]
            for ref in refs:
                resolved=(file.parent/ref).resolve()
                if boundary not in resolved.parents or not resolved.exists():raise ValueError('protected source escapes locked tree')
    else:
        kustomization=yaml.safe_load((root/source/'kustomization.yaml').read_text())
        if set(kustomization)-{'apiVersion','kind','resources'} or kustomization.get('resources')!=['resources.yaml']:
            raise ValueError('reuse requires a flat locked resource source without external rendering dependencies')
    for selected in paths:
        target=root/selected
        if not target.exists() or target.is_symlink() or (target.is_dir() and any(p.is_symlink() for p in target.rglob('*'))):
            raise ValueError('reuse source must exist and not contain symlinks')
    for command in [['git','cat-file','-e',commit+'^{commit}'],['git','merge-base','--is-ancestor',commit,'HEAD'],['git','diff','--exit-code',commit,'HEAD','--',*[str(p) for p in paths]]]:
        result=subprocess.run(command,cwd=root,capture_output=True)
        if result.returncode:raise ValueError('certified build source is unavailable or differs from current release')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);parser.add_argument('--contract',required=True);args=parser.parse_args()
    verify(args.commit,args.contract)
