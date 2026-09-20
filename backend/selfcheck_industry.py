"""行业赛道研判自检：跑几组合成行业事实，确认档位判定符合预期。

用法（在 backend 目录下）：
    .\.venv\Scripts\python.exe selfcheck_industry.py
"""
from app.industry import INDUSTRY_FIELDS, STAGES, evaluate, industry_queries, scan_stage

CASES: list[tuple[str, dict, str]] = [
    ("蓝海朝阳：高增长 + 政策扶持 + 无价格战 + 融资活跃", {
        "industry": "智能家居", "demand_signal": "快速增长", "growth_rate": 18,
        "policy_stance": "强扶持", "price_war": "无", "margin_trend": "上升",
        "hiring_trend": "扩张", "funding_events": 15, "capacity": "偏紧", "ipo_count": 2,
        "subsidy_dependency": False, "player_change": "缓慢增加", "salary_trend": "上涨", "region_fit": "强",
    }, "蓝海朝阳"),
    ("新势力：需求爆发 + 资本密集 + 供给不足", {
        "industry": "人形机器人", "demand_signal": "爆发", "growth_rate": 45,
        "policy_stance": "强扶持", "price_war": "无", "margin_trend": "上升",
        "hiring_trend": "大幅扩张", "funding_events": 40, "capacity": "严重不足", "ipo_count": 5,
        "subsidy_dependency": True, "player_change": "大量增加", "tech_disruption": "中",
    }, "新势力"),
    ("红海内卷：恶性价格战 + 毛利大幅下滑 + 产能过剩", {
        "industry": "传统彩电", "demand_signal": "放缓", "growth_rate": 1,
        "policy_stance": "中性", "price_war": "恶性", "margin_trend": "大幅下降",
        "hiring_trend": "收缩", "funding_events": 0, "capacity": "严重过剩", "player_change": "开始减少",
    }, "红海内卷"),
    ("夕阳：需求萎缩 + 负增长 + 玩家大量退出", {
        "industry": "传统燃油两轮车", "demand_signal": "萎缩", "growth_rate": -6,
        "policy_stance": "限制", "price_war": "激烈", "margin_trend": "下降",
        "hiring_trend": "大幅收缩", "funding_events": 0, "capacity": "严重过剩", "player_change": "大量退出",
    }, "夕阳"),
    ("政策强限制：即使需求稳定也压到红海", {
        "industry": "学科类培训", "demand_signal": "稳定", "growth_rate": 3,
        "policy_stance": "强限制", "price_war": "激烈", "margin_trend": "下降",
        "hiring_trend": "收缩", "funding_events": 1,
    }, "红海内卷"),
    ("平稳存量：增速与 GDP 同步 + 格局稳定", {
        "industry": "白色家电", "demand_signal": "稳定", "growth_rate": 5,
        "policy_stance": "扶持", "price_war": "局部", "margin_trend": "持平",
        "hiring_trend": "平稳", "funding_events": 4, "capacity": "基本平衡",
        "player_change": "基本稳定", "salary_trend": "持平", "region_fit": "强", "cr5": 70,
    }, "平稳存量"),
]


def main() -> int:
    print(f"五档：{' < '.join(s['name'] for s in STAGES)}")
    print(f"事实字段 {len(INDUSTRY_FIELDS)} 个\n")
    bad = 0
    for name, facts, expect in CASES:
        res = evaluate(facts)
        ok = expect in res["stage"]["name"]
        if not ok:
            bad += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"  期望 {expect} ｜ 实得 {res['stage']['name']}（{res['score']} 分，置信度 {int(res['confidence'] * 100)}%）"
              f" ｜ 进入结论：{res['stage']['entry_verdict']}")
        if res["caps"]:
            print(f"  硬性上限：{'；'.join(res['caps'])}")
        if res.get("gates"):
            print(f"  门槛未达：{'；'.join(res['gates'])}")
        if res["negative"]:
            print(f"  拖累因素：{'、'.join(res['negative'])}")
    print()
    demo = scan_stage("行业价格战激烈、产能过剩、需求萎缩、企业陆续退出，同时又有技术突破与渗透率提升")
    print("阶段特征词扫描：", {k: v for k, v in demo["counts"].items() if v})
    print("主导特征：", demo["dominant"])
    print("检索路数：", len(industry_queries("智能家居", "河南")))
    print(f"\n结果：{len(CASES) - bad}/{len(CASES)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
