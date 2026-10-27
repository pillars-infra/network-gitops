from copy import deepcopy
from test_ssa_release_executor import executor
from gateway_defaults import explicit_http_route_defaults


def route(spec):
    return {'apiVersion':'gateway.networking.k8s.io/v1','kind':'HTTPRoute','metadata':{'name':'demo','namespace':'demo'},'spec':spec}


def test_only_standard_missing_defaults_are_added_without_mutating_bundle():
    original=route({'parentRefs':[{'name':'edge'}],'rules':[{'backendRefs':[{'name':'app','port':80}]}]})
    before=deepcopy(original)
    result=explicit_http_route_defaults(original)
    assert result['spec']=={'parentRefs':[{'name':'edge','group':'gateway.networking.k8s.io','kind':'Gateway'}],
        'rules':[{'backendRefs':[{'name':'app','port':80,'group':'','kind':'Service','weight':1}],
                  'matches':[{'path':{'type':'PathPrefix','value':'/'}}]}]}
    assert original==before
    assert explicit_http_route_defaults(result)==result


def test_explicit_routing_and_non_gateway_parent_are_preserved():
    original=route({'parentRefs':[{'name':'parent','group':'example.org','kind':'CustomParent'}],
        'rules':[{'matches':[],'backendRefs':[{'name':'target','group':'example.org','kind':'CustomBackend','weight':0}]}]})
    assert explicit_http_route_defaults(original)==original
    for kind in ['TCPRoute','ConfigMap','Gateway']:
        item={**original,'kind':kind}
        assert explicit_http_route_defaults(item)==item
    assert explicit_http_route_defaults({**original,'apiVersion':'gateway.networking.k8s.io/v1beta1'})=={**original,'apiVersion':'gateway.networking.k8s.io/v1beta1'}


def test_executor_applies_default_equivalent_object_without_changing_source():
    source=route({'parentRefs':[{'name':'edge'}],'rules':[{'filters':[{'type':'RequestRedirect','requestRedirect':{'scheme':'https'}}]}]})
    before=deepcopy(source)
    applied=executor.Executor().with_audit([source],{'releaseId':'demo','operationId':'fixture'})[0]
    assert source==before
    assert applied['spec']==explicit_http_route_defaults(source)['spec']
    assert applied['metadata']['annotations']['delivery.re8ch.com/operation-id']=='fixture'
