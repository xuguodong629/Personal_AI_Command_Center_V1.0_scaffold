"""提示词版本化加载（规范 §21.3）：禁止在代码字符串里拼接长提示词。

提示词文件放在 `backend/prompts/<name>.vN.md`，YAML front-matter 声明
id / version / purpose / schema_version / risk，正文里用 `{{变量}}` 占位。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aios.core.config import PROJECT_ROOT

PROMPTS_DIR = PROJECT_ROOT / "backend" / "prompts"
_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@dataclass
class Prompt:
    id: str
    version: str
    purpose: str
    schema_version: str = "1"
    risk: str = ""
    system: str = ""
    template: str = ""
    path: str = ""

    def render(self, **variables: Any) -> str:
        missing = [k for k in set(_PLACEHOLDER.findall(self.template)) if k not in variables]
        if missing:
            raise KeyError(f"提示词 {self.id} 缺少变量：{', '.join(sorted(missing))}")
        return _PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), self.template)

    def with_variables(self, variables: dict[str, Any]) -> Prompt:
        return Prompt(id=self.id, version=self.version, purpose=self.purpose,
                      schema_version=self.schema_version, risk=self.risk, system=self.system,
                      template=self.render(**variables), path=self.path)


def _parse_meta(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta


def load_prompt(name: str) -> Prompt:
    """按名字加载提示词；文件不存在直接报错（不允许代码内兜底长提示词）。"""
    path = PROMPTS_DIR / name
    if not path.exists():
        matches = sorted(PROMPTS_DIR.glob(f"{name.split('.')[0]}*.md"))
        if not matches:
            raise FileNotFoundError(f"提示词不存在：{path}")
        path = matches[-1]
    text = path.read_text("utf-8")
    m = _FRONT_MATTER.match(text)
    if not m:
        raise ValueError(f"提示词缺少 front-matter：{path}")
    meta = _parse_meta(m.group(1))
    body = text[m.end():]
    system, _, template = body.partition("\n## 用户提示词\n")
    return Prompt(
        id=meta.get("id", name),
        version=meta.get("version", "0"),
        purpose=meta.get("purpose", "generic"),
        schema_version=meta.get("schema_version", "1"),
        risk=meta.get("risk", ""),
        system=system.strip(),
        template=template.strip(),
        path=str(path),
    )


def list_prompts() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        text = path.read_text("utf-8")
        m = _FRONT_MATTER.match(text)
        meta = _parse_meta(m.group(1)) if m else {}
        out.append({"file": path.name, "id": meta.get("id", ""), "version": meta.get("version", ""),
                    "purpose": meta.get("purpose", "")})
    return out
