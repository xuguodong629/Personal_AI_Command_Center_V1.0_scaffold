"""风控规则层自检：跑几组合成事实，确认规则与等级判定符合预期。

用法（在 backend 目录下）：
    .\.venv\Scripts\python.exe selfcheck_risk.py
"""
from app.risk import FACTS_FIELDS, RISK_DIMENSIONS, RiskFacts, evaluate

CASES: list[tuple[str, dict, str]] = [
    ("健康公司（大企业，实缴到位、参保充足）", {
        "company_name": "A 制造有限公司", "reg_capital": 5000, "paid_in_capital": 5000,
        "established": "2005-03", "status": "存续", "insured_count": 860,
        "claimed_headcount": 900, "website": True, "client_cases": True,
        "judicial_total": 2, "labor_disputes": 0, "contract_disputes": 1,
        "abnormal": False, "dishonest": False, "enforcement": 0,
    }, "绿"),
    ("典型空壳（集群注册＋零实缴＋零参保）", {
        "company_name": "B 商贸有限公司", "reg_capital": 50, "paid_in_capital": 0,
        "established": "2025-06", "status": "存续", "insured_count": 0,
        "claimed_headcount": 120, "address_type": "集群注册",
        "same_address_companies": 30, "website": False, "client_cases": False,
        "judicial_total": 0, "labor_disputes": 0,
    }, "橙/红"),
    ("老赖＋破产＋招聘收费（一票否决叠加）", {
        "company_name": "C 科技发展有限公司", "reg_capital": 1000, "paid_in_capital": 20,
        "established": "2019-05", "status": "存续", "insured_count": 4,
        "dishonest": True, "enforcement": 6, "enforcement_amount": 1800,
        "bankruptcy": "清算", "recruit_charging": True, "labor_disputes": 6,
    }, "红"),
    ("欠薪黑名单＋劳动争议集中＋宣称百人", {
        "company_name": "D 渠道服务有限公司", "reg_capital": 300, "paid_in_capital": 10,
        "established": "2020-08", "status": "存续", "insured_count": 3,
        "claimed_headcount": 200, "wage_arrears_listed": True, "labor_disputes": 8,
        "severance_disputes": 4, "social_arrears": True, "recruit_longterm": True,
    }, "红"),
    ("换壳史＋频繁更名＋关联企业批量注销", {
        "company_name": "E 实业有限公司", "reg_capital": 200, "paid_in_capital": 200,
        "established": "2012-04", "status": "存续", "insured_count": 40,
        "name_changes": 3, "related_deregistered": 5, "legal_rep_changes": 4,
        "judicial_total": 12, "contract_disputes": 7, "labor_disputes": 2,
    }, "橙"),
]


def main() -> int:
    print(f"风险维度 {len(RISK_DIMENSIONS)} 项 ｜ 事实字段 {len(FACTS_FIELDS)} 个")
    bad = 0
    for name, facts, expect in CASES:
        res = evaluate(RiskFacts(**facts))
        hit = f"{res['level']}" in expect or expect.startswith(res["level"])
        if not hit:
            bad += 1
        print(f"\n[{ 'PASS' if hit else 'FAIL' }] {name}")
        print(f"  期望 {expect} ｜ 实得 {res['level']}（{res['score']} 分）｜ 一票否决 {'是' if res['veto'] else '否'}"
              f" ｜ 完整度 {int(res['confidence'] * 100)}%")
        for f in res["findings"][:4]:
            print(f"    - [{f['severity_label']}] {f['title']}")
        if len(res["findings"]) > 4:
            print(f"    …… 共 {len(res['findings'])} 条")
    print(f"\n结果：{len(CASES) - bad}/{len(CASES)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
