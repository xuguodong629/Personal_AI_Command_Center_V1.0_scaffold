"""验证：检索摘要里的 JD 能被抽出来（正文抓不到时也成立）。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import _extract_job_candidate  # noqa: E402

CASES = [
    ("设计师渠道部-渠道运营主管", "https://jobs.51job.com/hangzhou-lpq/172391181.html", "",
     "一、核心工作职责 1.落地执行：承接渠道运营经理策略，负责所辖区域标杆城市（2-3 个/人）渠道攻坚落地，含城市筛选、政策签约、目标分解、活动落地全流程跟进。"),
    ("商务产品经理（郑州）(J13622)招聘| 郑州金水区| 2.5-5万| 曙光信息",
     "https://jobs.51job.com/jinshuiqu/171740552.html",
     "这是抓到的拦截页噪声文字，没有任何职责内容",
     "招聘商务产品经理(郑州)，工作地点郑州金水区，薪资2.5-5万，要求本科、3-5年经验，负责深入调研商务团队销售流程与渠道管理。"),
    ("家电渠道经理- 郑州商贸有限公司 - 领英",
     "https://cn.linkedin.com/jobs/view/abc",
     "",
     "职位来源于智联招聘。【岗位职责】 1、负责客户开发、需求跟进、客户拜访、合同签约等工作； 2、深入挖掘客户需求，结合产品核心优势达成合作。"),
]

for title, url, text, snippet in CASES:
    r = _extract_job_candidate(title, url, text, snippet)
    print(f"证据={r['_证据']:<8} 岗位={r['岗位'][:24]:<26} 公司={r['公司'][:16]:<18} 地区={r['地区']} 薪资={r['薪资']}")
    print(f"        JD = {r['_JD要点'][:100]}")
    jd = r["_JD要点"]
    ok = len(jd) >= 24 and any(s in jd for s in ("职责", "负责", "要求", "经验", "熟悉"))
    print(f"        jd_verdict 通过 = {ok}")
    print()
