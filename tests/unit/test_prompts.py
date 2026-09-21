"""提示词外置单元测试（规范 §21.3：提示词必须有版本、可审查，且不得内联在代码里）。"""
from __future__ import annotations

import pytest
from aios.modules.ai_gateway.prompts import PROMPTS_DIR, list_prompts, load_prompt

pytestmark = pytest.mark.unit


def test_given_prompt_file_when_loaded_then_front_matter_parsed():
    prompt = load_prompt("job_extraction.v1.md")
    assert prompt.id == "job_extraction"
    assert prompt.version == "1"
    assert prompt.purpose == "job_extraction"
    assert "不可信" in prompt.system          # 提示注入防护说明必须在系统提示里
    assert "{{material}}" in prompt.template


def test_given_variables_when_rendered_then_placeholders_replaced():
    prompt = load_prompt("job_extraction.v1.md").with_variables({"material": "郑州 渠道经理 15-20K"})
    assert "{{material}}" not in prompt.template
    assert "郑州 渠道经理 15-20K" in prompt.template


def test_given_missing_variable_when_rendered_then_keyerror():
    with pytest.raises(KeyError):
        load_prompt("job_extraction.v1.md").render()


def test_given_prompts_dir_when_listed_then_has_version_metadata():
    entries = list_prompts()
    assert entries, f"提示词目录为空：{PROMPTS_DIR}"
    assert all(e["id"] and e["version"] and e["purpose"] for e in entries)
