"""用用户实际报告里的两条"表一岗位"回归 V2 规则：它们该不该进具体岗位池？

数据来源：用户贴回的真实报告 表六/表九 ——
  ① 河南万宝股份有限公司 · 家电销售（开封）· 年薪5-10万 · 领英(转智联) · 有 JD（25-35岁/大专以上/有销售经验优先）
  ② 河南赫耀环境科技 · 美的家用电器，零售+批发销售（焦作）· BOSS直聘 · JD「经验不限/学历不限」（极简）
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.jobs import JobQueryContext, classify, score_job  # noqa: E402

# 用户这次 GUI 运行的口径（河南/郑州 + 家电渠道 + 12-18k 期望）
CTX = JobQueryContext(regions=["河南", "郑州"], keywords=["渠道经理", "区域经理", "渠道销售"],
                     industries=["家电"], salary_min=12000, salary_max=18000, exp_years="5-10")

ROWS = [
    {
        "岗位": "家电销售", "公司": "河南万宝股份有限公司", "地区": "开封",
        "薪资": "年薪5-10万", "经验/学历要求": "25-35岁 大专以上",
        "来源平台": "领英", "链接": "https://cn.linkedin.com/jobs/view/家电销售-开封-at-河南万宝股份有限公司-4421075983",
        "JD 要点": "25-35岁，大专以上学历，有销售经验优先，负责门店家电销售与客户接待。",
        "风险标记": "材料未见",
    },
    {
        "岗位": "美的家用电器，零售+批发销售", "公司": "河南赫耀环境科技",
        "地区": "焦作", "薪资": "材料未见", "经验/学历要求": "经验不限/学历不限",
        "来源平台": "BOSS直聘",
        "链接": "https://www.zhipin.com/job_detail/cd3e38c54b090d5103x_2tu0FlJT.html",
        "JD 要点": "经验不限，学历不限。",
        "风险标记": "材料未见",
    },
]

print("=== 用户报告里进「表一」的 2 条，按 V2 规则的判定 ===\n")
for r in ROWS:
    v = classify(r, CTX, material="")
    s = score_job(r, CTX, v["status"])
    print(f"· {r['岗位']} | {r['公司']} | {r['地区']}")
    print(f"  判定 = {v['status']}   岗位评分 = {s['score']}（{s['layer']}）")
    print(f"  门槛 = {v['gates']}")
    print(f"  原因 = {v['reasons']}")
    print(f"  扣分 = {s['reasons']}")
    print(f"  薪资维度 = {[p for p in s['parts'] if p['维度'] == '薪资匹配'][0]}")
    print()

print("=== 结论 ===")
for r in ROWS:
    v = classify(r, CTX, material="")
    ok = v["status"] == "verified"
    print(f"[{'该进表一' if ok else '不该进表一'}] {r['公司']} → {v['status']}")
