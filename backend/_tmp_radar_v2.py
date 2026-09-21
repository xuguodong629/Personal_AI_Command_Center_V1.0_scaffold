"""V2.0 规则层验收：真实跑一次岗位雷达，输出判定结果与假岗位检查。

用法（backend 目录）：.\.venv\Scripts\python.exe _tmp_radar_v2.py
"""
import io
import json
import sys
import time

import httpx

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8787"
LOGS = r"G:\个人文件\项目运作\软件开发测试\Personal_AI_Command_Center_V1.0_scaffold\data\logs"
FULL = "--full" in sys.argv          # 全开四路信号（与 V1 的 14 路可比）
OUT = "radar-res-v2-full.json" if FULL else "radar-res-v2.json"

REQ = {
    "provider_id": "p_mu803jvmrcsz",
    # 与前端 local-defaults.json 完全一致的默认口径（徐国栋画像）
    "position_keywords": "区域经理 渠道经理 渠道销售 区域销售 大客户销售 城市负责人",
    "regions": "河南 郑州 新乡 洛阳 开封 南阳 信阳 商丘",
    "industries": "家电 厨电 耐用消费品 净水 消费电子 智能家居",
    "target_companies": "美的,海尔,格力,海信,TCL,老板电器,方太,华帝,万和,A.O.史密斯,九阳,苏泊尔,施耐德电气,西门子,博西家电",
    "resume_summary": "徐国栋，33 岁，13 年耐用消费品/家电渠道操盘经验，base 河南新乡。美的（厨电/净水）、海尔（统帅/空调）成熟体系，最大操盘 5000 万级，回款率连续 100%。",
    "profile": "目标岗位：区域经理/渠道经理/城市负责人；目标地区：河南省内；期望薪资 12000–18000 元/月。底线：必须有明确岗位 JD 与可点开的原始招聘链接；不接受公司主页/招聘入口。",
    "scope": "all",
    "salary_min": 12000,
    "salary_max": 18000,
    "exp_years": "5-10",
    "job_type": "全职",
    "publish_days": 30,
    "want_count": 30,
    "batch": 0,
    "risk_scan": True,
    "growth_scan": True,
    "review_scan": True,
    "policy_scan": True,
}

with open(f"{LOGS}\\radar-req{'-full' if FULL else ''}.json", "w", encoding="utf-8") as f:
    json.dump(REQ, f, ensure_ascii=False, indent=2)

t0 = time.time()
with httpx.Client(timeout=900.0) as c:
    r = c.post(f"{BASE}/api/ai/direct/radar", json=REQ)
print(f"HTTP {r.status_code}  {time.time() - t0:.0f}s  (signals full={FULL})")
res = r.json()
with open(f"{LOGS}\\{OUT}", "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)

if not res.get("ok"):
    print("FAILED:", json.dumps(res, ensure_ascii=False)[:2000])
    raise SystemExit(1)

pool = res.get("pool") or {}
items = pool.get("items") or pool.get("rows") or []
print(f"\npool: rows={pool.get('rows')} batch={pool.get('batch')}")
diag = res.get("diagnostics") or {}
print(f"检索路数={diag.get('paths')} 引擎={diag.get('engine')}")
for q in (diag.get("job_detail_paths") or []):
    print(f"  路: {q}")
print(f"信号: {json.dumps(res.get('signals', {}).get('summary', {}), ensure_ascii=False)[:420]}")
ver = res.get("verification") or {}
print(f"verification: {json.dumps(ver, ensure_ascii=False)[:600]}")

# ---- 材料质量：报告里真正出现的「岗位页 / 官方社招页」域名计数 ----
content = res.get("content") or ""
print("\n=== 材料结构（报告正文里出现的域名）===")
for dom, label in (("jobs.51job.com", "前程无忧岗位页(可抓正文)"), ("51job.com", "前程无忧其他"),
                   ("zhaopin.com", "智联招聘"), ("zhipin.com", "BOSS直聘(登录墙)"),
                   ("liepin.com", "猎聘(登录墙)"), ("recruit.midea.com", "美的官方社招"),
                   ("maker.haier.net", "海尔官方社招"), ("gree.com", "格力官网"),
                   ("campus", "校招页"), ("yingjiesheng", "应届生求职网"),
                   ("jobs-worldwide", "LinkedIn聚合页")):
    n = content.count(dom)
    if n:
        print(f"  {label:<26} × {n}")

print("\n--- 具体岗位池 ---")
for it in items:
    print(f"· {it.get('岗位')} | {it.get('公司')} | {it.get('地区')} | {it.get('薪资')} | "
          f"评分={it.get('_score')}({it.get('_layer')}) | 状态={it.get('_job_status')}")
    if it.get("_score_reasons"):
        print(f"    扣分原因：{it['_score_reasons']}")
    print(f"    链接：{it.get('链接')}")

pend = res.get("pending_jobs") or {}
print(f"\n--- 待核实（{pend.get('rows')} 条）---")
for it in (pend.get("items") or [])[:12]:
    print(f"· {it.get('岗位')} | {it.get('公司')} | {it.get('地区')} | 原因={it.get('_job_reasons')}")
watch = res.get("company_watchlist") or {}
intel = res.get("industry_intel") or {}
print(f"\n公司监控：{watch.get('rows')} 条 ｜ 行业情报：{intel.get('rows')} 条")

# ---- 假岗位硬检查 ----
BAD_TITLE = ("招聘入口", "招聘主页", "全部职位", "职位列表", "岗位列表", "热门职位", "加入我们",
             "校园招聘", "校招", "应届", "行业", "新闻", "资讯", "政策", "融资", "扩产", "投产",
             "上市", "并购", "中标", "相关岗位", "岗位需求", "人才需求", "站内检索", "未覆盖")
BAD_URL = ("companydetail", "careers", "campus", "socialhome", "jobs-worldwide", "joinus")

print("\n=== 假岗位硬检查 ===")
bad_t, bad_u, missing = [], [], []
for it in items:
    t = (it.get("岗位") or "")
    u = (it.get("链接") or "").lower()
    if any(x in t for x in BAD_TITLE):
        bad_t.append(t)
    if any(x in u for x in BAD_URL):
        bad_u.append(f"{t} → {u}")
    if not it.get("_score"):
        missing.append(t)
print(f"[{'PASS' if not bad_t else 'FAIL'}] 情报/入口类标题混入具体岗位池：{bad_t or '无'}")
print(f"[{'PASS' if not bad_u else 'FAIL'}] 公司主页/招聘入口链接混入：{bad_u or '无'}")
print(f"[{'PASS' if not missing else 'FAIL'}] 岗位池条目缺岗位评分：{missing or '无'}")
scores = [int(it.get("_score") or 0) for it in items]
print(f"[INFO] 岗位评分区间：{min(scores) if scores else '-'} ~ {max(scores) if scores else '-'}"
      f"；公司评分字段 _company_score 仅出现在监控表")
