"""Explicit HTTPRoute v1 defaults for stable SSA atomic-list ownership.

Defaults are defined by the Gateway API schema, never copied from live routes.
https://gateway-api.sigs.k8s.io/reference/api-spec/1.4/spec/
"""
from copy import deepcopy


def explicit_http_route_defaults(item: dict) -> dict:
    result = deepcopy(item)
    if (result.get('apiVersion'), result.get('kind')) != ('gateway.networking.k8s.io/v1', 'HTTPRoute'):
        return result
    spec = result.get('spec', {})
    for parent in spec.get('parentRefs', []):
        parent.setdefault('group', 'gateway.networking.k8s.io')
        parent.setdefault('kind', 'Gateway')
    for rule in spec.get('rules', []):
        rule.setdefault('matches', [{'path': {'type': 'PathPrefix', 'value': '/'}}])
        for backend in rule.get('backendRefs', []):
            backend.setdefault('group', '')
            backend.setdefault('kind', 'Service')
            backend.setdefault('weight', 1)
    return result
