"""Short-lived runner HTTP adapter; the existing SSA executor remains the writer."""
from __future__ import annotations

import contextlib
import base64
import os
import ssl
import yaml
import http.server
import http.client
import json
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from http_stream import copy_response

MAIN_API = "https://kube-api.service.re8ch.com"
CLOUD_PROXY = "/api/v1/namespaces/ai-operations/services/re8ch-cloud-platform:19443/proxy/k8s/"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def no_redirect_open(request, *, timeout=120):
    config_path=os.environ.get("KUBECONFIG")
    context=ssl.create_default_context()
    handler=urllib.request.HTTPSHandler(context=context)
    if config_path:
        config=yaml.safe_load(Path(config_path).read_text())
        current=next(c['context'] for c in config['contexts'] if c['name']==config['current-context'])
        if current['cluster'] not in {'re8ch','re8ch-main'}:
            raise ValueError('managed transport requires the main control-plane context')
        cluster=next(c['cluster'] for c in config['clusters'] if c['name']==current['cluster'])
        endpoint=urllib.parse.urlsplit(cluster['server'])
        original=urllib.parse.urlsplit(request.full_url)
        expected=urllib.parse.urlsplit(MAIN_API)
        if (endpoint.scheme!='https' or endpoint.username or endpoint.password
                or endpoint.path not in {'','/'} or endpoint.query or endpoint.fragment
                or original.scheme!=expected.scheme or original.netloc!=expected.netloc
                or cluster.get('insecure-skip-tls-verify') or not cluster.get('certificate-authority-data')):
            raise ValueError('managed transport requires the reviewed main endpoint and public CA')
        context=ssl.create_default_context(cadata=base64.b64decode(cluster['certificate-authority-data'],validate=True).decode())
        tls_name=cluster.get('tls-server-name') or endpoint.hostname
        class MainConnection(http.client.HTTPSConnection):
            def connect(self):
                http.client.HTTPConnection.connect(self)
                self.sock=self._context.wrap_socket(self.sock,server_hostname=tls_name)
        class MainHTTPS(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(MainConnection,req,context=context)
        handler=MainHTTPS(context=context)
        # Use the same selected endpoint, CA and SNI as the outer native client;
        # never copy its user credentials or turn off certificate verification.
        url=urllib.parse.urlunsplit((endpoint.scheme,endpoint.netloc,original.path,original.query,''))
        request=urllib.request.Request(url,data=request.data,headers=dict(request.header_items()),method=request.get_method())
    return urllib.request.build_opener(NoRedirect(),handler).open(request,timeout=timeout)


def verify_self(binding_digest, token_source, *, open_url=no_redirect_open):
    token = token_source()
    if not token:
        raise ValueError("self binding requires the original execution identity")
    url = MAIN_API + CLOUD_PROXY.removesuffix("k8s/") + "cluster-bindings/re8ch"
    request = urllib.request.Request(url, headers={"Authorization":"Bearer "+token,
        "X-Re8ch-Execution-Proof":"Bearer "+token, "X-Re8ch-Cluster-Binding":binding_digest})
    try:
        with open_url(request, timeout=30) as response:
            binding = json.load(response)
    except Exception:
        raise ValueError("self cluster binding verification failed") from None
    if binding.get("clusterRef") != "re8ch" or binding.get("bindingDigest") != binding_digest or not binding.get("clusterIdentityRef") or not binding.get("apiServiceRef"):
        raise ValueError("self cluster binding identity mismatch")
    return binding


@contextlib.contextmanager
def transport(cluster_ref, binding_digest, token_source, *, release_id, open_url=no_redirect_open):
    """Only this command's loopback socket exists; proofs never enter argv/files."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def forward(self):
            target = urllib.parse.urlsplit(self.path)
            if target.scheme or target.netloc or not target.path.startswith("/"):
                self.send_error(400)
                return
            token = token_source()
            if not token:
                self.send_error(401)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else None
            headers = {key: self.headers[key] for key in ("Content-Type", "Accept", "Accept-Encoding") if self.headers.get(key)}
            headers["Authorization"] = "Bearer " + token
            url = MAIN_API + self.path
            if cluster_ref != "re8ch":
                headers.update({"X-Re8ch-Execution-Proof": "Bearer " + token,
                                "X-Re8ch-Release-Id": release_id, "X-Re8ch-Cluster-Binding": binding_digest})
                url = MAIN_API + CLOUD_PROXY + urllib.parse.quote(cluster_ref, safe="") + self.path
            request = urllib.request.Request(url,
                                             data=body, headers=headers, method=self.command)
            try:
                response = open_url(request, timeout=120)
            except urllib.error.HTTPError as error:
                response = error
            except Exception:
                self.send_error(502, "managed cluster request failed")
                return
            with response:
                self.send_response(response.status)
                for key in ("Content-Type", "Content-Encoding", "Warning", "Audit-Id"):
                    for value in response.headers.get_all(key, []):
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                copy_response(response, self.connection, self.wfile)
            self.close_connection = True

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = forward

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="re8ch-target-transport-") as directory:
            config = Path(directory) / "kubeconfig"
            config.write_text(json.dumps({"apiVersion": "v1", "kind": "Config",
                "clusters": [{"name": cluster_ref, "cluster": {"server": f"http://127.0.0.1:{server.server_port}"}}],
                "users": [{"name": "request-local", "user": {}}],
                "contexts": [{"name": cluster_ref, "context": {"cluster": cluster_ref, "user": "request-local"}}],
                "current-context": cluster_ref}))
            config.chmod(0o600)
            yield str(config)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
