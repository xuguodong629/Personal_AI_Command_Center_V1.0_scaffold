"""渠道业务知识库自检：业务域完整性、套话检测准确性、追问模板、提示词注入。

离线运行、不调用模型。
用法（backend 目录）：.\.venv\Scripts\python.exe selfcheck_channel.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.channel import (  # noqa: E402
    DOMAINS, FOLLOWUP_TEMPLATES, all_followups_text, analyze_answer, analyze_text,
    domains_for_stage, domains_text,
)

ok_all = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok_all
    ok_all &= cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" → {detail}" if detail else ""))


def main() -> int:
    # ① 业务域完整性
    check("12 个业务域", len(DOMAINS) == 12, "、".join(d["name"] for d in DOMAINS))
    required = {"id", "name", "metrics", "questions", "platitude", "concrete", "evaluate"}
    missing = [(d.get("id"), required - set(d)) for d in DOMAINS if required - set(d)]
    check("每域字段齐全", not missing, str(missing) if missing else "id/name/metrics/questions/platitude/concrete/evaluate")
    thin = [d["id"] for d in DOMAINS if len(d["questions"]) < 3]
    check("每域至少 3 个具体问题", not thin, f"不足的域：{thin}" if thin else "全部 ≥3 问")
    vague = [q for d in DOMAINS for q in d["questions"] if "你怎么做的" in q or "有什么成果" in q]
    check("题库里没有空问", not vague, str(vague) if vague else "无「你怎么做的」类问题")
    check("每域都有套话对照", all(d["platitude"].startswith("❌") and d["concrete"].startswith("✅") for d in DOMAINS))

    # ② 阶段轮换取域
    a = domains_for_stage("professional", 1)
    b = domains_for_stage("professional", 2)
    check("专业阶段取 4 个域", len(a) == 4, "、".join(d["name"] for d in a))
    check("不同题轮换不同域", a[0]["id"] != b[0]["id"], f"题1 {a[0]['id']} vs 题2 {b[0]['id']}")
    check("反问阶段不注入题库", domains_for_stage("ask", 1) == [])
    check("履历阶段有专属域", len(domains_for_stage("resume", 1)) >= 3)

    # ③ 套话 vs 具体 的判定
    plat = analyze_answer("我们团队深度赋能终端，通过闭环管理和打法拉通，实现全链路协同发力，全面提升终端势能。")
    check("套话回答判为「套话为主」", plat["verdict"] == "套话为主", f"{plat['verdict']} ｜ 套话分 {plat['platitude_score']} ｜ 词 {[h['term'] for h in plat['platitude_hits']]}")
    check("套话回答列出缺失维度", len(plat["missing"]) >= 3, "；".join(plat["missing"]))

    conc = analyze_answer("滑县回款 3000 万（出货 3400 万、零售 2600 万），一级商 6 家，"
                          "月返 2 个点、账期 30 天；库存周转 61 天，超期 600 台折让 11 个点；"
                          "单店投入 8 万、月销 60 台、毛利 22%、8 个月回本。")
    check("具体回答判为「具体」", conc["verdict"] == "具体", f"{conc['verdict']} ｜ 数字 {conc['digits']} 个 ｜ 业务名词 {len(conc['business_terms'])} 个")
    check("具体回答识别出多个业务名词", len(conc["business_terms"]) >= 8, "、".join(conc["business_terms"][:12]))

    half = analyze_answer("我负责区域操盘，做了渠道优化和团队激励，业绩有提升。")
    check("含糊回答不判为「具体」", half["verdict"] in ("偏泛", "缺业务细节", "套话为主"), f"{half['verdict']}（数字 {half['digits']}）")

    short = analyze_answer("嗯，还行吧。")
    check("过短回答单独判定", short["verdict"] == "过短", short["verdict"])

    # ④ 提示词注入文本
    stats = analyze_text(plat["platitude_hits"] and "我们深度赋能终端，闭环打法。" or "")
    check("检测块含套话命中与要求", ("套话命中" in stats and "必须用业务机制问题追问" in stats), stats.splitlines()[1][:60])
    biz = domains_text("professional", 1, count=2)
    check("业务题库块含机制要求", ("业务题库" in biz and "禁止问「你怎么做的」" in biz), biz.splitlines()[0][:50])
    check("业务题库块含套话对照", "套话对照" in biz)
    fu = all_followups_text()
    check("追问模板含四类", all(k in fu for k in ("口径", "结构", "算法", "对价")), f"{len(FOLLOWUP_TEMPLATES)} 组模板")

    print(f"\n结果：{'全部通过' if ok_all else '存在失败项'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
