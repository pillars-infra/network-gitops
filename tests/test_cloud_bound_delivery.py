"""Bound target and main-state separation through the actual executor interfaces."""
import base64
import contextlib
import gzip
import http.server
import json
import os
from pathlib import Path
import subprocess
import threading
import urllib.request

import pytest
import yaml
import test_ssa_release_executor as base
import cluster_transport
import operation_materialize as materialize
import profile
from unified_bundle import canonical, digest

ROOT=Path(__file__).parents[1]


def test_actual_kubectl_keeps_original_proof_binding_and_gzip(monkeypatch):
    seen=[]
    class API(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path,self.headers.get('Authorization'),self.headers.get('X-Re8ch-Execution-Proof'),self.headers.get('X-Re8ch-Release-Id'),self.headers.get('X-Re8ch-Cluster-Binding')))
            # Kubernetes proxy may strip Authorization; the dedicated proof is
            # still the original caller, not the Cloud ServiceAccount identity.
            assert self.headers.get('X-Re8ch-Execution-Proof')=='Bearer synthetic-proof'
            body=gzip.compress(json.dumps({'gitVersion':'synthetic-atlantic','payload':'x'*8192}).encode())
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Encoding','gzip');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),API);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(cluster_transport,'MAIN_API',f'http://127.0.0.1:{server.server_port}');monkeypatch.delenv('KUBECONFIG',raising=False)
    try:
        with cluster_transport.transport('re8ch-atlantic','b'*64,lambda:'synthetic-proof',release_id='scoped-release') as path:
            config=yaml.safe_load(Path(path).read_text());assert config['users'][0]['user']=={}
            assert 'synthetic-proof' not in Path(path).read_text()
            r=subprocess.run(['kubectl','--kubeconfig',path,'get','--raw=/version'],capture_output=True,text=True,timeout=10)
            assert r.returncode==0,r.stderr
            assert json.loads(r.stdout)['payload']=='x'*8192
        assert not Path(path).exists()
        assert seen[0]==(cluster_transport.CLOUD_PROXY+'re8ch-atlantic/version','Bearer synthetic-proof','Bearer synthetic-proof','scoped-release','b'*64)
    finally:server.shutdown();server.server_close();thread.join()


def test_executor_wraps_only_business_commands_without_mutating_outer_identity(tmp_path,monkeypatch):
    outer=tmp_path/'main';outer.write_text('main control-plane identity');monkeypatch.setenv('KUBECONFIG',str(outer))
    seen=[]
    @contextlib.contextmanager
    def transport(ref,binding,token,**kw):
        seen.append((ref,binding,kw['release_id']));yield 'request-local-config'
    monkeypatch.setattr(cluster_transport,'transport',transport)
    runner=lambda argv,**kwargs:subprocess.CompletedProcess(argv,0,'ok','')
    ex=base.executor.Executor(runner=runner);c=base.contract();c['spec']['target'].update(cluster='re8ch-atlantic',clusterBindingDigest='a'*64)
    ex.bind_cluster_target(c);r=ex.command(['kubectl','get','configmap','canary'])
    assert r.args[:3]==['kubectl','--kubeconfig','request-local-config']
    assert os.environ['KUBECONFIG']==str(outer) and outer.read_text()=='main control-plane identity'
    assert seen==[('re8ch-atlantic','a'*64,'demo')]


def test_self_binding_failure_never_falls_back_to_direct_main(monkeypatch):
    monkeypatch.setattr(cluster_transport,'verify_self',lambda *a:(_ for _ in ()).throw(ValueError('stale UID')))
    ex=base.executor.Executor(runner=lambda *a,**k:pytest.fail('must not run kubectl'))
    c=base.contract();c['spec']['target']['clusterBindingDigest']='a'*64;ex.bind_cluster_target(c)
    with pytest.raises(base.executor.Rejected,match='self cluster binding'):ex.command(['kubectl','get','configmap','canary'])


@pytest.mark.parametrize('action',['reset','reconcile','force-reconcile'])
def test_all_operation_modes_reject_cross_target_and_binding_state(tmp_path,action):
    c,op,bundle=base.prepare(tmp_path);ex=base.executor.Executor(runner=base.Runner(),now=lambda:base.NOW);state_root=tmp_path/'state'
    ex.reconcile(c,op,bundle,state_root,verify_signature=False)
    store=base.executor.Store(state_root,'demo');state=store.state()
    for wrong in [{'clusterRef':'re8ch-atlantic'},{'clusterRef':'re8ch','clusterBindingDigest':'b'*64}]:
        updated={**state,**wrong};store.accept(updated)
        current=json.loads(json.dumps(c));current['spec']['target']['clusterBindingDigest']='a'*64
        operation={**op,'operationId':__import__('uuid').uuid4().__str__(),'sequence':2,'action':action,'contractDigest':digest(canonical(current))}
        with pytest.raises(base.executor.Rejected,match='another cluster'):ex.validate(current,operation,bundle,store)


def test_cached_result_does_not_bypass_target_validation(tmp_path):
    c,op,bundle=base.prepare(tmp_path);ex=base.executor.Executor(runner=base.Runner(),now=lambda:base.NOW);root=tmp_path/'state';ex.reconcile(c,op,bundle,root,verify_signature=False)
    c['spec']['target']['cluster']='re8ch-atlantic'
    with pytest.raises(base.executor.Rejected,match='target mismatch'):ex.validate(c,op,bundle,base.executor.Store(root,'demo'))


def test_hydrate_reuse_and_state_persist_reject_another_target(tmp_path):
    c,op,bundle=base.prepare(tmp_path);root=tmp_path/'state';ex=base.executor.Executor(runner=base.Runner(),now=lambda:base.NOW);ex.reconcile(c,op,bundle,root,verify_signature=False)
    state=base.executor.Store(root,'demo').state();state['clusterRef']='re8ch-atlantic'
    cm={'metadata':{'name':materialize.state_configmap_name('demo'),'namespace':'demo','resourceVersion':'1'},'data':{'accepted-state.json':json.dumps(state)}}
    cp=tmp_path/'cm.json';cp.write_text(json.dumps(cm));contract=tmp_path/'contract.yaml';contract.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError,match='another cluster'):materialize.hydrate(cp,tmp_path/'hydrate','demo',contract)
    with pytest.raises(ValueError,match='another cluster'):materialize.accepted_bundle(cp,contract)
    (root/'state/demo.json').write_text(json.dumps(state))
    with pytest.raises(ValueError,match='another cluster'):materialize.state_patch(cp,root,'demo',tmp_path/'missing-result',tmp_path/'patch',contract)


def test_bound_profile_controls_main_without_new_oidc_and_rejects_unbound_remote(tmp_path,monkeypatch):
    monkeypatch.setattr(profile,'ROOT',tmp_path);(tmp_path/'contracts').mkdir();monkeypatch.chdir(tmp_path)
    for side,cluster in [('self','re8ch'),('atlantic','re8ch-atlantic')]:
        name=f'networking-native-{side}-cloud-target-canary';c=yaml.safe_load((ROOT/f'operations/releases/conformance-contracts/{name}.yaml.template').read_text());path=Path('contracts')/f'{name}.yaml'
        path.write_text(yaml.safe_dump(c))
        with pytest.raises(ValueError,match='binding'):profile.validate_contract(path,for_execution=True)
        c['spec']['target']['clusterBindingDigest']='a'*64;path.write_text(yaml.safe_dump(c));result=profile.validate_contract(path,for_execution=True)
        assert result['cluster']==cluster and result['control-cluster']=='re8ch'
        assert result['audience']==profile.AUDIENCE and result['environment']==profile.ENVIRONMENT
    c['metadata']['name']='networking-native-legacy';c['spec']['source']['path']='releases/networking-native-legacy';c['spec']['target'].pop('clusterBindingDigest');p=Path('contracts/networking-native-legacy.yaml');p.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError,match='legacy remote'):profile.validate_contract(p,for_execution=True)


def test_state_seeds_never_enter_runtime_inventory_and_have_only_exact_main_rbac():
    import compile_native
    docs=list(yaml.safe_load_all((ROOT/'clusters/re8ch/cloud-target-delivery-bootstrap.yaml').read_text()));files,ledger=compile_native.project(docs)
    assert not ledger['releases'] and len(ledger['platformBootstrap'])==4
    role=next(o for o in docs if o['kind']=='Role')
    assert role['rules'][0]['resourceNames']==[materialize.state_configmap_name('networking-native-'+s+'-cloud-target-canary') for s in ['self','atlantic']]
    assert role['rules'][0]['verbs']==['get','patch']
    assert role['rules'][1]['resourceNames']==['re8ch-cloud-target-canary']


def test_all_workflow_state_paths_remain_main_and_validate_contract_scope():
    workflow=yaml.safe_load((ROOT/'.github/workflows/static-release.yml').read_text())
    for job in ['execute','runtime-dry-run']:
        steps=workflow['jobs'][job]['steps'];acquire=next(s for s in steps if s.get('name')=='Acquire exact OIDC identity')
        assert acquire['env']['TARGET_CLUSTER']=='${{ needs.validate.outputs.control-cluster }}'
        assert 'export KUBECONFIG="$kubeconfig"' in acquire['run']
        for step in steps:
            run=step.get('run','')
            if 'operation_materialize.py hydrate ' in run:assert 'hydrate --contract "$CONTRACT"' in run
            if 'operation_materialize.py state-patch ' in run:assert 'state-patch --contract "$CONTRACT"' in run
    assert '--for-execution' in workflow['jobs']['validate']['steps'][-2]['run'] or any('--for-execution' in s.get('run','') for s in workflow['jobs']['validate']['steps'])


def test_real_tls_keeps_native_selected_endpoint_ca_and_sni(tmp_path,monkeypatch):
    import ssl
    import urllib.error
    # Ephemeral test-only keys, generated in pytest's temporary directory.
    cert,key=tmp_path/'cert.pem',tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=main.transport.test','-addext','subjectAltName=DNS:main.transport.test'],check=True,capture_output=True)
    class API(http.server.BaseHTTPRequestHandler):
        def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'{"gitVersion":"tls-fixture"}')
        def log_message(self,*a):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),API);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key);server.socket=ctx.wrap_socket(server.socket,server_side=True);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    cfg={'current-context':'main','contexts':[{'name':'main','context':{'cluster':'re8ch'}}], 'clusters':[{'name':'re8ch','cluster':{'server':f'https://127.0.0.1:{server.server_port}','tls-server-name':'main.transport.test','certificate-authority-data':base64.b64encode(cert.read_bytes()).decode()}}], 'users':[{'name':'ignored','user':{'token':'must-not-be-forwarded'}}]}
    path=tmp_path/'main-config';path.write_text(yaml.safe_dump(cfg));monkeypatch.setenv('KUBECONFIG',str(path))
    try:
        with cluster_transport.no_redirect_open(urllib.request.Request(cluster_transport.MAIN_API+'/version')) as r:assert json.load(r)['gitVersion']=='tls-fixture'
        cfg['clusters'][0]['cluster']['tls-server-name']='wrong.transport.test';path.write_text(yaml.safe_dump(cfg))
        with pytest.raises(urllib.error.URLError):cluster_transport.no_redirect_open(urllib.request.Request(cluster_transport.MAIN_API+'/version'))
        cfg['clusters'][0]['cluster']['insecure-skip-tls-verify']=True;path.write_text(yaml.safe_dump(cfg))
        with pytest.raises(ValueError,match='reviewed main'):cluster_transport.no_redirect_open(urllib.request.Request(cluster_transport.MAIN_API+'/version'))
    finally:server.shutdown();server.server_close();t.join()


def test_repeated_operation_audit_is_stable_and_rollback_uses_previous_artifact():
    ex=base.executor.Executor();obj={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'canary','namespace':'default','annotations':{'delivery.re8ch.com/operation-id':'legacy'}}}
    op={'releaseId':'release','operationId':'first','bundle':{'digest':'sha256:'+'a'*64}}
    first=ex.with_audit([obj],op);second=ex.with_audit([obj],{**op,'operationId':'second'})
    assert first==second
    assert 'delivery.re8ch.com/operation-id' not in first[0]['metadata']['annotations']
    rollback=ex.with_audit([obj],op,artifact_digest='sha256:'+'b'*64)
    assert rollback[0]['metadata']['annotations']['delivery.re8ch.com/artifact-digest']=='sha256:'+'b'*64


def test_actual_self_verification_keeps_original_business_caller(monkeypatch):
    seen=[]
    class API(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path,self.headers.get('Authorization'),self.headers.get('X-Re8ch-Execution-Proof')))
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            if self.path.endswith('/cluster-bindings/re8ch'):
                self.wfile.write(json.dumps({'clusterRef':'re8ch','bindingDigest':'a'*64,'clusterIdentityRef':{'uid':'synthetic-identity'},'apiServiceRef':{'uid':'synthetic-service'}}).encode())
            else:self.wfile.write(b'{"gitVersion":"synthetic-self"}')
        def log_message(self,*a):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),API);t=threading.Thread(target=server.serve_forever,daemon=True);t.start();monkeypatch.delenv('KUBECONFIG',raising=False);monkeypatch.setattr(cluster_transport,'MAIN_API',f'http://127.0.0.1:{server.server_port}')
    try:
        ex=base.executor.Executor();ex.actions_kube_token=lambda:'synthetic-original-proof';c=base.contract();c['spec']['target']['clusterBindingDigest']='a'*64;ex.bind_cluster_target(c)
        result=ex.command(['kubectl','get','--raw=/version'],timeout=10)
        assert json.loads(result.stdout)['gitVersion']=='synthetic-self'
        assert seen[0][1:]==('Bearer synthetic-original-proof','Bearer synthetic-original-proof')
        assert seen[-1]==('/version','Bearer synthetic-original-proof',None)
    finally:server.shutdown();server.server_close();t.join()


def test_actual_watch_streams_before_eof_and_cancels_upstream(monkeypatch):
    import select
    cancelled=threading.Event()
    class API(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"type":"ADDED"}\n');self.wfile.flush()
            readable,_,_=select.select([self.connection],[],[],5)
            if readable and not self.connection.recv(1):cancelled.set()
        def log_message(self,*a):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),API);t=threading.Thread(target=server.serve_forever,daemon=True);t.start();monkeypatch.delenv('KUBECONFIG',raising=False);monkeypatch.setattr(cluster_transport,'MAIN_API',f'http://127.0.0.1:{server.server_port}')
    try:
        with cluster_transport.transport('re8ch-atlantic','a'*64,lambda:'synthetic-proof',release_id='scoped-release') as config:
            p=subprocess.Popen(['kubectl','--kubeconfig',config,'--request-timeout=1s','get','--raw=/watch?watch=true'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                assert select.select([p.stdout],[],[],3)[0]
                assert 'ADDED' in p.stdout.readline()
                p.wait(timeout=5)
                assert cancelled.wait(3)
            finally:
                if p.poll() is None:p.kill();p.wait()
    finally:server.shutdown();server.server_close();t.join()


def test_observer_never_reads_main_for_a_different_operation_target(tmp_path,monkeypatch):
    import shutil
    import observe_runtime
    c,op,bundle=base.prepare(tmp_path);op['target']='re8ch-atlantic/demo'
    (tmp_path/'operation.json').write_text(json.dumps(op));(tmp_path/'pulled').mkdir();shutil.copyfile(bundle,tmp_path/'pulled/release.bundle')
    monkeypatch.setattr(observe_runtime,'Executor',lambda:pytest.fail('cross-target observation must not construct a client'))
    result=observe_runtime.observe(tmp_path,contract=c)
    assert result['health']['status']=='unknown'
