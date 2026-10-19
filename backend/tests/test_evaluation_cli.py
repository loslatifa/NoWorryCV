import importlib.util
import json
from pathlib import Path
import sys

import pytest

from backend.app.core.config import get_settings

SCRIPT=Path(__file__).resolve().parents[2]/"scripts/evaluate_quality.py"


def load_cli():
    spec=importlib.util.spec_from_file_location("quality_cli_test",SCRIPT)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_override_only_changes_the_current_process_and_not_env_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER","qwen")
    monkeypatch.setenv("QWEN_API_KEY","fake-test-key")
    monkeypatch.setenv("QWEN_MODEL","original-model")
    output=tmp_path/"report.json"
    local_env=SCRIPT.parents[1]/".env"
    before=local_env.read_bytes() if local_env.exists() else None
    def fake_evaluation(*args, **kwargs):
        assert get_settings().qwen_model=="evaluation-only-model"
        assert get_settings().llm_strict_mode
        return {"passed":True,"cases":[],"regressions":[]}
    monkeypatch.setattr("backend.app.services.evaluation.evaluate_dataset",fake_evaluation)
    monkeypatch.setattr(sys,"argv",[str(SCRIPT),"--provider","configured","--model","evaluation-only-model","--output",str(output)])
    assert load_cli().main()==0
    assert json.loads(output.read_text())["passed"]
    assert (local_env.read_bytes() if local_env.exists() else None)==before


@pytest.mark.parametrize("source",["--dataset","--baseline"])
def test_cli_cannot_overwrite_an_input_file(monkeypatch, tmp_path, source):
    original=tmp_path/"source.json";original.write_text("original bytes")
    monkeypatch.setattr(sys,"argv",[str(SCRIPT),source,str(original),"--output",str(original)])
    with pytest.raises(SystemExit) as raised:load_cli().main()
    assert raised.value.code==2 and original.read_text()=="original bytes"


def test_cli_rejects_a_model_override_in_stub_mode(monkeypatch):
    monkeypatch.setattr(sys,"argv",[str(SCRIPT),"--provider","stub","--model","unused"])
    with pytest.raises(SystemExit) as raised:load_cli().main()
    assert raised.value.code==2
