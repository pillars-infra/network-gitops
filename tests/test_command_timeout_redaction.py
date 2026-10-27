import subprocess
import traceback
import pytest
from test_ssa_release_executor import executor

@pytest.mark.parametrize('phase',['get','preflight'])
def test_timeout_retains_type_without_credential_argv_or_captured_streams(monkeypatch,phase):
    def runner(argv,**kwargs):
        assert '--token=fixture-credential' in argv
        raise subprocess.TimeoutExpired(argv,19,output='fixture-captured-output',stderr='fixture-captured-error')
    instance=executor.Executor(runner=runner)
    monkeypatch.setattr(instance,'actions_kube_token',lambda:'fixture-credential')
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        if phase=='get':instance.command(['kubectl','get','deployment','demo'])
        else:instance.apply([{'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'demo','namespace':'demo'}}],'fixture-manager',dry_run=True)
    error=caught.value
    assert error.cmd==['kubectl'] and error.timeout==19
    assert error.output is None and error.stderr is None and error.__suppress_context__
    rendered=''.join(traceback.format_exception(type(error),error,error.__traceback__))
    assert 'fixture-credential' not in rendered
    assert 'fixture-captured-output' not in rendered and 'fixture-captured-error' not in rendered
