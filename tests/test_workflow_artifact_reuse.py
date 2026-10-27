from pathlib import Path
import yaml


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
