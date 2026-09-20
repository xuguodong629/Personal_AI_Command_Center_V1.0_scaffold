"""机会池条数与去重自检：验证表一解析（用于「换一批」）是否可靠。

用法（在 backend 目录下）：
    .\.venv\Scripts\python.exe selfcheck_pool.py
"""
from app.ai import _extract_pool_rows, _rows_block

DEMO = """本次仅覆盖部分岗位。

## 表一 · 机会池总表（必须放最前面）

| 级 | 岗位 | 公司 | 地区 | 来源平台 | 链接 | 风险标记 | JD 要点 |
|---|---|---|---|---|---|---|---|
| 高 | 区域经理 | 海信 | 郑州 | 公众号 | [2.1] | 材料未见 | 五险一金 |
| 中 | 渠道经理 | 美的集团 | 河南 | 汇总号 | [3.1][3.2] | 材料未见 | 渠道体系 |
| 低（行业不符） | 大区经理 | 海尔智家 | 郑州 | 校招号 | [4.3] | 材料未见 | 校招 |

## 表二 · 加权评分总览

| 公司/机会 | 加权总分 | 分层 |
|---|---|---|
| 海信·区域经理 | 74 | 谨慎 |
"""


def main() -> int:
    rows = _extract_pool_rows(DEMO)
    print(f"解析条数：{len(rows)}（期望 3）")
    for r in rows:
        print(f"  {r.get('公司', '')} · {r.get('岗位', '')} ｜ 级={r.get('级', '')}")
    keys = [f"{r.get('公司', '')}·{r.get('岗位', '')}" for r in rows]
    print("换一批排除串：", "；".join(keys))
    print("排除块预览：", _rows_block(rows).strip()[:80])

    # 逐项校验：整行结构（列名 → 单元格）必须完整可用
    checks = {
        "解析出 3 行": len(rows) == 3,
        "公司列正确": rows[0].get("公司") == "海信",
        "岗位列正确": rows[0].get("岗位") == "区域经理",
        "风险标记列存在": "风险标记" in rows[0],
        "JD 要点列存在": any("JD" in k for k in rows[0]),
        "带括号的级能保留": rows[2].get("级", "").startswith("低"),
        "空输入安全返回": _extract_pool_rows("没有表格的报告") == [],
    }
    for name, cond in checks.items():
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    ok = all(checks.values())
    print(f"\n结果：{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
