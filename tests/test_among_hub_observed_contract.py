"""The promoted Hub CRD contract must retain fields consumed by target binding."""
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_import_observation_fields_are_declared_in_reviewed_bootstrap_schema():
    ledger = json.loads((ROOT / 'operations/releases/helm-authority.json').read_text())
    crd = next(o for o in ledger['platformBootstrap'] if o.get('kind') == 'CustomResourceDefinition'
        and o['metadata']['name'] == 'importedservices.peering.re8ch.com')
    schema = next(v for v in crd['spec']['versions'] if v['name'] == 'v1alpha1')[
        'schema']['openAPIV3Schema']['properties']['status']['properties']
    for key, kind in [('observedGeneration', 'integer'), ('advertisementUID', 'string'),
                      ('advertisementGeneration', 'integer'), ('advertisementResourceVersion', 'string')]:
        assert schema[key]['type'] == kind
    assert schema['publicIngress']['x-kubernetes-preserve-unknown-fields'] is True
    assert schema['expiresAt']['format'] == 'date-time'


def test_scoped_grant_schema_preserves_names_and_uses_kubernetes_native_sets():
    ledger=json.loads((ROOT/'operations/releases/helm-authority.json').read_text())
    crds=[o for o in ledger['platformBootstrap'] if o.get('kind')=='CustomResourceDefinition'
          and o['metadata']['name'].endswith('.peering.re8ch.com')]
    grant=next(o for o in crds if o['metadata']['name']=='managedaccessgrants.peering.re8ch.com')
    rules=grant['spec']['versions'][0]['schema']['openAPIV3Schema']['properties']['spec']['properties']['rules']
    assert rules['items']['properties']['resourceNames']=={'type':'array','items':{'type':'string','minLength':1}}
    def check(value):
        if isinstance(value,dict):
            assert value.get('uniqueItems') is not True
            for child in value.values():check(child)
        elif isinstance(value,list):
            for child in value:check(child)
    for crd in crds:check(crd)
