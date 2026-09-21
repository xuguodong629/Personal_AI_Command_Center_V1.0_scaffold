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
    "position_keywords": "区域经理 渠道经理 渠道销售",
    "regions": "河南 郑州",
    "industries": "家电 智能家居",
    "resume_summary": "徐国栋，10 年家电行业渠道与区域销售管理经验，做过省区渠道体系搭建、经销商开发与 KA 客户维护。",
    "profile": "候选人底线：必须有明确岗位 JD 与可点开的原始招聘链接；不接受公司主页/招聘入口。",
    "scope": "all",
    "salary_min": 10000,
    "salary_max": 20000,
    "exp_years": "5-10",
    "job_type": "全职",
    "publish_days": 7,
    "want_count": 20,
    "batch": 0,
    "risk_scan": True,
    "growth_scan": True,
    "review_scan": FULL,
    "policy_scan": FULL,
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
print(f"信号: {json.dumps(res.get('signals', {}).get('summary', {}), ensure_ascii=False)[:400]}")
ver = res.get("verification") or {}
print(f"verification: {json.dumps(ver, ensure_ascii=False)[:600]}")

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
