import json
import subprocess
from pathlib import Path
import yaml
import pytest
from test_ssa_release_executor import prepare,executor,Runner,NOW
import select_accepted_releases as selector
import refresh_kubeconfig


def fixture(tmp_path):
    value,op,bundle=prepare(tmp_path)
    root=tmp_path/'state'
    executor.Executor(runner=Runner(),now=lambda:NOW).reconcile(value,op,bundle,root,False)
    state=executor.Store(root,'demo').state();state['bundleReference']='oci://ghcr.io/pillars-infra/network-gitops-release/demo'
    path=tmp_path/'contract.yaml';path.write_text(yaml.safe_dump(value))
    entry={'release-id':'demo','namespace':'demo','contract':'contract.yaml'}
    cm={'metadata':{'name':'ssa-state-demo','namespace':'demo'},'data':{'accepted-state.json':json.dumps(state)}}
    return entry,cm,state


@pytest.mark.parametrize('fault',[None,'missing','empty','blocked','suspended','unhealthy','foreign','malformed','read-error','timeout'])
def test_selection_reads_only_exact_state_and_never_selects_invalid_acceptance(tmp_path,fault):
    entry,cm,state=fixture(tmp_path)
    if fault in ['blocked','suspended']:state[fault]=True
    elif fault=='unhealthy':state['healthyDigest']='sha256:'+'0'*64
    elif fault=='foreign':state['bundleReference']='oci://attacker.invalid/demo'
    elif fault=='malformed':state={'healthyDigest':'invalid'}
    cm['data']['accepted-state.json']=json.dumps(state)
    if fault=='empty':cm['data']={}
    calls=[]
    def runner(argv,**kwargs):
        calls.append(argv)
        if fault=='timeout':raise subprocess.TimeoutExpired(['kubectl','private'],10)
        return subprocess.CompletedProcess(argv,1 if fault=='read-error' else 0,'' if fault=='missing' else json.dumps(cm),'private diagnostics')
    selected,skipped,invalid=selector.select([entry],tmp_path,runner,sleeper=lambda _:None)
    expected=['kubectl','get','configmap','ssa-state-demo','--namespace','demo','--ignore-not-found','-o','json']
    assert calls==([expected]*3 if fault=='timeout' else [expected])
    if fault is None:assert selected==[entry] and not skipped and not invalid
    elif fault in ['foreign','malformed','read-error','timeout']:assert not selected and invalid and not skipped
    else:assert not selected and skipped and not invalid
    assert 'private' not in json.dumps([selected,skipped,invalid])


def test_invalid_selection_does_not_block_valid_release(tmp_path):
    entry,cm,_=fixture(tmp_path)
    broken={**entry,'release-id':'broken'}
    def runner(argv,**kwargs):
        return subprocess.CompletedProcess(argv,0,json.dumps(cm) if argv[3]=='ssa-state-demo' else '[]','')
    selected,_,invalid=selector.select([broken,entry],tmp_path,runner)
    assert selected==[entry] and invalid==[('broken','invalid-or-changed-acceptance')]


def test_selection_retries_only_transient_transport_failures(tmp_path):
    entry,cm,_=fixture(tmp_path);calls=[];delays=[]
    failures=['Unable to connect to the server: EOF','net/http: TLS handshake timeout']
    def runner(argv,**kwargs):
        calls.append(argv)
        if failures:return subprocess.CompletedProcess(argv,1,'',failures.pop(0))
        return subprocess.CompletedProcess(argv,0,json.dumps(cm),'')
    selected,skipped,invalid=selector.select([entry],tmp_path,runner,sleeper=delays.append)
    assert selected==[entry] and not skipped and not invalid
    assert len(calls)==3 and delays==[1,2]


def test_selection_does_not_retry_authorization_failure(tmp_path):
    entry,_,_=fixture(tmp_path);calls=[]
    def runner(argv,**kwargs):
        calls.append(argv);return subprocess.CompletedProcess(argv,1,'','forbidden')
    selected,skipped,invalid=selector.select([entry],tmp_path,runner,sleeper=lambda _:None)
    assert not selected and not skipped and invalid==[('demo','state-read-failed')]
    assert len(calls)==1


def test_empty_matrix_is_explicitly_skipped_and_execution_rechecks_state():
    root=Path(__file__).resolve().parents[1]
    text=(root/'.github/workflows/networking-reconcile.yml').read_text();workflow=yaml.safe_load(text)
    assert workflow['jobs']['reconcile']['if']=="needs.select.outputs.has-accepted == 'true'"
    assert 'SOPS_AGE_KEY' not in yaml.safe_dump(workflow['jobs']['select'])
    assert 'id-token' in workflow['jobs']['select']['permissions']
    assert any('accepted-bundle --configmap' in step.get('run','') for step in workflow['jobs']['reconcile']['steps'])
    assert workflow['jobs']['selection-status']['steps'][0]['run'].rstrip().endswith('exit 1')


def test_initialize_creates_private_fixed_config_without_output_or_overwrite(tmp_path,monkeypatch,capsys):
    path=tmp_path/'kubeconfig';monkeypatch.setenv('KUBECONFIG',str(path));monkeypatch.setenv('KUBE_API_CA','fixture-ca')
    monkeypatch.setattr(refresh_kubeconfig.Executor,'actions_kube_token',lambda self:'fixture-token')
    refresh_kubeconfig.initialize();value=yaml.safe_load(path.read_text())
    assert path.stat().st_mode&0o777==0o600
    assert value['clusters'][0]['cluster']['server']=='https://kube-api.service.re8ch.com'
    assert value['clusters'][0]['cluster']['tls-server-name']=='kube-api.re8ch.com'
    assert value['users'][0]['user']['token']=='fixture-token'
    assert capsys.readouterr()==('','')
    with pytest.raises(FileExistsError):refresh_kubeconfig.initialize()


def test_empty_selector_outputs_skip_flag(tmp_path,monkeypatch):
    import sys
    output=tmp_path/'output';summary=tmp_path/'summary'
    monkeypatch.setattr(selector,'replay_matrix',lambda:[])
    monkeypatch.setattr(sys,'argv',['selector','--github-output',str(output),'--summary',str(summary)])
    selector.main()
    assert 'matrix={"include":[]}\n' in output.read_text()
    assert 'has-accepted=false\n' in output.read_text()
    assert 'invalid=0\n' in output.read_text()
