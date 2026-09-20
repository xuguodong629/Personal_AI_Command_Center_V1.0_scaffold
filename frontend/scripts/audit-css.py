"""CSS 审计：找重复选择器、未使用样式、未定义类名、硬编码颜色。

用法（项目根目录或 frontend 目录）：
    python frontend/scripts/audit-css.py            # 概览
    python frontend/scripts/audit-css.py --full     # 打印全部明细

说明：TSX 里的动态类名（`toast-${kind}`、`sev-${s}`、三元里的字符串）都会被识别，
      动态前缀会以「前缀*」形式参与匹配，避免误报"未定义"。
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
CSS = SRC / "styles.css"

CLASS_RE = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")
STR_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"|`([^`]*)`")


def css_classes() -> tuple[Counter, dict[str, list[int]]]:
    text = CSS.read_text("utf-8")
    counts: Counter = Counter()
    where: dict[str, list[int]] = defaultdict(list)
    for i, line in enumerate(text.splitlines(), 1):
        for m in CLASS_RE.finditer(line):
            counts[m.group(1)] += 1
            where[m.group(1)].append(i)
    return counts, where


def _brace_block(text: str, start: int) -> str:
    """从 className={ 的位置读取配对的花括号内容。"""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:start + 400]


def tsx_classes() -> tuple[Counter, set[str]]:
    counts: Counter = Counter()
    prefixes: set[str] = set()
    for p in SRC.rglob("*.tsx"):
        text = p.read_text("utf-8")
        for m in re.finditer(r"className=", text):
            i = m.end()
            if i < len(text) and text[i] == '"':
                blobs = [text[i + 1:text.find('"', i + 1)]]
            elif i < len(text) and text[i] == "{":
                blobs = [g for tup in STR_RE.findall(_brace_block(text, i)) for g in tup if g]
            else:
                continue
            for blob in blobs:
                # 模板字面量里 ${...} 前面的片段若是前缀（以 - 结尾）→ 记为动态前缀
                for chunk in re.split(r"\$\{[^}]*\}", blob):
                    for token in chunk.split():
                        if token.endswith("-") or token.endswith("_"):
                            prefixes.add(token)
                        elif token:
                            counts[token] += 1
    return counts, prefixes


def main() -> int:
    full = "--full" in sys.argv
    text = CSS.read_text("utf-8")
    css, where = css_classes()
    used, prefixes = tsx_classes()

    print(f"styles.css：{len(text.splitlines())} 行 ｜ CSS 类 {len(css)} 个 ｜ TSX 静态类 {len(used)} 个 ｜ 动态前缀 {len(prefixes)} 个")

    print("\n① 重复定义的选择器（同一类名出现 ≥3 次；基础类 + 变体属正常，需逐条确认）")
    for c, n in css.most_common(12):
        if n >= 3:
            print(f"   .{c} × {n}（行 {', '.join(map(str, where[c][:8]))}）")

    def covered(c: str) -> bool:
        return c in css or any(c.startswith(p) for p in prefixes)

    zombie = sorted(c for c in css if c not in used and not covered(c))
    print(f"\n② 只在 CSS 出现、TSX 未使用（僵尸样式）{len(zombie)} 个")
    print("   " + (", ".join(zombie[:70]) if zombie else "无"))

    missing = sorted(c for c in used if c not in css and not any(c.startswith(p) for p in prefixes))
    print(f"\n③ TSX 用到但 CSS 未定义（可能没生效）{len(missing)} 个")
    print("   " + (", ".join(missing[:70]) if missing else "无"))

    # 硬编码颜色：排除主题变量定义区（前 120 行）
    head = "\n".join(text.splitlines()[:120])
    body_lines = text.splitlines()[120:]
    body = "\n".join(body_lines)
    colors = Counter(COLOR_RE.findall(body))
    hexes = {c: n for c, n in colors.items() if c.startswith("#")}
    print(f"\n④ 硬编码颜色（变量定义区之外）：hex {len(hexes)} 种 ｜ rgba/函数色 {len(colors) - len(hexes)} 种")
    for c, n in sorted(hexes.items(), key=lambda kv: -kv[1]):
        lines = [i + 121 for i, ln in enumerate(body_lines) if c in ln][:6]
        print(f"   {c} × {n}（行 {', '.join(map(str, lines))}）")
    theme_hits = sum(1 for line in body_lines if "var(--" in line)
    print(f"   使用主题变量的行数：{theme_hits} ｜ 仍含硬编码的行数：{sum(1 for ln in body_lines if COLOR_RE.search(ln))}")

    if full:
        print("\n--- 全部僵尸样式 ---\n" + ", ".join(zombie))
        print("\n--- 全部缺失样式 ---\n" + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
