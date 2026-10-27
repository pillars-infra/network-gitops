from pathlib import Path
import yaml
import pytest
import subprocess
import shutil
import sys


def test_reuse_never_compiles_and_only_reads_same_contract_registry_digest():
    workflow=yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/static-release.yml').read_text())
    jobs=workflow['jobs']
    assert "inputs.mode == 'publish'" in jobs['compile-sign']['if']
    for name in ['execute','runtime-dry-run']:
        job=jobs[name]
        step=next(s for s in job['steps'] if 'REUSE_DIGEST' in s.get('env',{}))
        assert '^sha256:[0-9a-f]{64}$' in step['run']
        assert 'OCI_REFERENCE="oci://ghcr.io/pillars-infra/network-gitops-release/$RELEASE_ID"' in step['run']
        assert step['run'].index('cosign verify')<step['run'].index('flux pull artifact')
        assert job['environment']=='${{ needs.validate.outputs.environment }}'


@pytest.fixture
def source_repo(tmp_path):
    import verify_reuse_source
    root=tmp_path/'repo';root.mkdir()
    def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    git('init','-q');git('config','user.email','test@example.invalid');git('config','user.name','Fixture');git('config','commit.gpgsign','false')
    (root/'contracts').mkdir();(root/'releases/demo').mkdir(parents=True)
    (root/'contracts/demo.yaml').write_text(yaml.safe_dump({'spec':{'source':{'path':'releases/demo'}}}))
    (root/'releases/demo/kustomization.yaml').write_text('resources: [resources.yaml]\n')
    (root/'releases/demo/resources.yaml').write_text('kind: ConfigMap\n')
    git('add','.');git('commit','-qm','fixture');commit=git('rev-parse','HEAD')
    return root,commit,git,verify_reuse_source.verify

def test_reuse_accepts_unrelated_main_changes(source_repo):
    root,commit,git,verify=source_repo
    (root/'README.md').write_text('unrelated');git('add','.');git('commit','-qm','unrelated')
    verify(commit,'contracts/demo.yaml',root)

@pytest.mark.parametrize('fault',['content','contract','unknown','ref','external','symlink'])
def test_reuse_rejects_changed_source_missing_commit_and_external_dependencies(source_repo,fault):
    root,commit,git,verify=source_repo
    if fault=='content':(root/'releases/demo/resources.yaml').write_text('kind: Service\n')
    if fault=='contract':(root/'contracts/demo.yaml').write_text(yaml.safe_dump({'spec':{'source':{'path':'releases/demo'},'changed':True}}))
    if fault=='unknown':commit='f'*40
    if fault=='ref':commit='HEAD'
    if fault=='external':(root/'releases/demo/kustomization.yaml').write_text('resources: [resources.yaml]\ncomponents: [../../external]\n')
    if fault=='symlink':(root/'releases/demo/link').symlink_to('/tmp')
    git('add','.');subprocess.run(['git','commit','-qm','change'],cwd=root,capture_output=True)
    with pytest.raises(ValueError):verify(commit,'contracts/demo.yaml',root)


@pytest.fixture
def protected_repo(tmp_path):
    import verify_reuse_source
    root=tmp_path/'protected';root.mkdir()
    actual=Path(__file__).resolve().parents[1]
    for name in ['clusters/re8ch','charts','schemas']:
        shutil.copytree(actual/name,root/name)
    (root/'operations/releases').mkdir(parents=True)
    for name in ['helm-lock.json','advanced-fabric-inventory.json','compile_protected_helm.py','compile_helm.py','compile_native.py','restricted_configmap.py','restricted_object.py','unified_bundle.py','operation_materialize.py','profile.py']:
        shutil.copyfile(actual/'operations/releases'/name,root/'operations/releases'/name)
    contract='contracts/networking-helm-advanced-fabric-kube-system.yaml'
    (root/'contracts').mkdir();shutil.copyfile(actual/contract,root/contract)
    def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    git('init','-q');git('config','user.email','test@example.invalid');git('config','user.name','Fixture');git('config','commit.gpgsign','false');git('add','.');git('commit','-qm','fixture')
    return root,git('rev-parse','HEAD'),git,verify_reuse_source.verify,contract

@pytest.mark.parametrize('fault',['compiler','inventory','overlay','chart','escape','symlink'])
def test_protected_reuse_binds_full_source_closure(protected_repo,fault):
    root,commit,git,verify,contract=protected_repo
    verify(commit,contract,root)
    paths={'compiler':'operations/releases/compile_protected_helm.py','inventory':'operations/releases/advanced-fabric-inventory.json','overlay':'clusters/re8ch/advanced-fabric-control-plane-offload.yaml','chart':'operations/releases/helm-lock.json'}
    if fault in paths:
        p=root/paths[fault];p.write_text(p.read_text()+'\n')
    elif fault=='escape':
        (root/'clusters/re8ch/kustomization.yaml').write_text('resources: [../../outside.yaml]\n')
        (root/'outside.yaml').write_text('kind: ConfigMap\n')
    else:(root/'clusters/re8ch/unreviewed').symlink_to('/tmp')
    git('add','.');git('commit','-qm','changed')
    with pytest.raises(ValueError):verify(commit,contract,root)
