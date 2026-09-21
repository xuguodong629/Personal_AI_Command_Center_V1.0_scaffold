"""岗位真实性判定自检（岗位雷达改造验收用）。

覆盖规格里的测试 A–E，外加链接编造、引用核验、地区匹配、岗位评分与公司评分分离。
离线运行，不调用模型、不花额度。

用法（backend 目录）：.\.venv\Scripts\python.exe selfcheck_jobs.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.jobs import (  # noqa: E402
    JobQueryContext, classify, parse_salary, process_report, score_job, split_sections,
)

CTX = JobQueryContext(
    regions=["河南", "郑州"],
    keywords=["区域经理", "渠道经理", "渠道销售"],
    industries=["家电", "智能家居"],
    salary_min=10000,
    salary_max=20000,
    exp_years="5-10",
    job_type="全职",
)

ok_all = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok_all
    ok_all &= cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" → {detail}" if detail else ""))


def main() -> int:
    material = "[3.1] 郑州 区域销售经理 招聘 https://www.liepin.com/job/123.shtml\n[4.2] 洛阳 渠道经理 招聘"

    print("=== 测试 A：真实岗位 → verified ===")
    a = {
        "岗位": "区域销售经理", "公司": "XX家电有限公司", "地区": "郑州", "薪资": "15-20K",
        "福利保障": "五险一金", "经验/学历要求": "5-10年 本科", "发布时间": "近 7 天",
        "来源平台": "BOSS直聘", "链接": "https://www.zhipin.com/job_detail/abc.html",
        "JD 要点": "负责河南区域渠道开发与经销商维护，完成年度销售指标，要求5年以上家电渠道经验。",
        "风险标记": "未命中风险关键词",
    }
    ra = classify(a, CTX, material)
    check("A 判定为 verified", ra["status"] == "verified", f"{ra['status']} ｜ {ra['reasons']}")
    sa = score_job(a, CTX, ra["status"])
    check("A 岗位评分 ≥80（优先投递）", sa["score"] >= 80, f"{sa['score']} 分 · {sa['layer']}")

    print("\n=== 测试 B：公司招聘入口 / 泛指岗位 → 不得进 pool ===")
    b = {
        "岗位": "渠道销售岗", "公司": "美的集团", "地区": "材料未见", "薪资": "材料未见",
        "来源平台": "站内检索", "链接": "https://www.midea.com/careers",
        "JD 要点": "JD未覆盖", "风险标记": "材料未见",
    }
    rb = classify(b, CTX, material)
    check("B 不得为 verified", rb["status"] in ("invalid", "pending"), f"{rb['status']} ｜ {rb['reasons'][:2]}")
    b2 = {"岗位": "渠道/区域销售岗（JD 未覆盖，站内检索）", "公司": "美的集团", "地区": "材料未见",
          "来源平台": "站内检索", "链接": "公司招聘主页", "JD 要点": "站内检索"}
    rb2 = classify(b2, CTX, material)
    check("B2 泛指岗位判 invalid", rb2["status"] == "invalid", f"{rb2['status']} ｜ {rb2['reasons'][:2]}")

    print("\n=== 测试 C：行业新闻/公司情报 → 不得生成岗位 ===")
    for title in ("家电行业销售人才需求增加", "美的集团扩产投产公告", "某公司完成B轮融资",
                  "公司招聘入口", "2026届校园招聘公告", "区域销售岗位需求", "相关岗位"):
        rc = classify({"岗位": title, "公司": "某公司", "地区": "河南", "来源平台": "官网",
                       "链接": "https://x.com/a", "JD 要点": "负责渠道拓展与客户维护工作，要求三年以上经验"}, CTX, material)
        check(f"C 拒绝「{title}」", rc["status"] == "invalid", rc["status"])

    print("\n=== 测试 D：真实岗位但地区不匹配 → 不进目标区域岗位池 ===")
    d = dict(a, 地区="成都", 链接="https://www.zhipin.com/job_detail/cd.html")
    rd = classify(d, CTX, material)
    check("D 地区不符 → 非 verified", rd["status"] == "pending", f"{rd['status']} ｜ {rd['reasons'][:1]}")
    sd = score_job(d, CTX, rd["status"])
    check("D 地区匹配项得 0 分", [p for p in sd["parts"] if p["维度"] == "地区匹配"][0]["得分"] == 0,
          f"总分 {sd['score']}")

    print("\n=== 测试 E：只有公司情报/新闻/入口 → 具体岗位必须允许 0 条 ===")
    report_e = """一句话说明。

## 表一 · 今日具体岗位
| 岗位 | 公司 | 地区 | 薪资 | 福利保障 | 经验/学历要求 | 发布时间 | 来源平台 | 链接 | JD要点 | 风险标记 |
|---|---|---|---|---|---|---|---|---|---|---|
| （本批 0 条具体岗位） | 材料未见 | — | — | — | — | — | — | — | 材料中未出现明确岗位JD | — |

## 表二 · 待核实岗位
| 岗位 | 公司 | 地区 | 薪资 | 来源平台 | 链接 | 缺什么 | 下一步怎么核实 |
|---|---|---|---|---|---|---|---|
| 渠道销售岗 | 美的集团 | 材料未见 | 材料未见 | 站内检索 | 官网招聘主页 | 缺地点与JD | 站内检索确认在招岗位 |

## 表三 · 目标公司监控
| 公司 | 为什么值得监控 | 依据 | 监控动作 |
|---|---|---|---|
| 美的集团 | 河南渠道下沉、扩产 | [2.1] | 每月看官网招聘页 |

## 表四 · 行业情报
| 主题 | 内容 | 依据 | 对我们的意义 |
|---|---|---|---|
| 以旧换新 | 政策落地带动县域备货 | [5.1] | 渠道岗需求可能上升 |
"""
    re_ = process_report(report_e, CTX, material)
    check("E 具体岗位 = 0（正确结果）", re_["stats"]["verified"] == 0, f"{re_['stats']}")
    check("E 待核实 ≥1", re_["stats"]["pending"] >= 1, "、".join(x.get("岗位", "") for x in re_["pending"]))
    check("E 公司监控 ≥1", re_["stats"]["watch"] >= 1, "、".join(x.get("公司", "") for x in re_["watch"]))
    check("E 行业情报 ≥1", re_["stats"]["intel"] >= 1, "、".join(x.get("主题", "") for x in re_["intel"]))
    check("E pool.items 不含泛指岗位",
          all("岗" not in (x.get("岗位") or "")[-1:] or "经理" in (x.get("岗位") or "") for x in re_["pool"]),
          str([x.get("岗位") for x in re_["pool"]]))

    print("\n=== 附加：链接与引用核验 / 字段占位 / 薪资解析 ===")
    rf = classify(dict(a, 链接="[9.9]"), CTX, material)
    check("编造的引用编号判为缺失链接", "引用编号在材料中不存在" in " ".join(rf["reasons"]), rf["reasons"][:2])
    rg = classify(dict(a, 链接="[3.1]"), CTX, material)
    check("材料中真实存在的引用可作链接凭据", rg["status"] == "verified", rg["status"])
    rh = classify(dict(a, **{"JD 要点": "材料未见"}), CTX, material)
    check("JD 占位 → pending", rh["status"] == "pending", rh["reasons"][:2])
    check("薪资解析 15-20K", parse_salary("15-20K·13薪") == (15000, 20000), str(parse_salary("15-20K·13薪")))
    check("薪资解析 年薪 15-30万 折月", parse_salary("年薪15-30万") == (12500, 25000), str(parse_salary("年薪15-30万")))

    print("\n=== 附加：分段解析 ===")
    secs = split_sections(report_e)
    check("四段都能切出", all(secs[k] for k in ("pool", "pending", "watch", "intel")),
          " / ".join(f"{k}:{len(secs[k])}字" for k in ("pool", "pending", "watch", "intel")))

    print("\n=== 附加：岗位评分与公司评分离（同名键不同） ===")
    row = dict(a)
    sc = score_job(row, CTX, "verified")
    check("岗位评分写入 _score（非公司分）", "_score" not in row and sc["score"] > 0,
          f"岗位评分 {sc['score']}（公司评分由 _attach_company_scores 写 _company_score）")
    check("岗位评分含 7 个维度", len(sc["parts"]) == 7, "、".join(p["维度"] for p in sc["parts"]))

    print("\n=== V2 新增：公司主页链接 / 行业黑名单 / 刷量降权 / 薪资只看筛选器 ===")
    from app.jobs import industry_verdict, verify_jobs  # noqa: E402

    rv1 = classify(dict(a, 链接="https://www.midea.com/careers"), CTX, material)
    check("公司主页(careers)链接 → 不得 verified", rv1["status"] == "pending", rv1["reasons"][:2])
    rv1b = classify(dict(a, 链接="https://www.midea.com/companydetail/123"), CTX, material)
    check("公司详情页(companydetail)链接 → 不得 verified", rv1b["status"] == "pending", rv1b["reasons"][:1])

    rv2 = classify(dict(a, 公司="XX食品有限公司"), CTX, material)
    s2 = score_job(dict(a, 公司="XX食品有限公司"), CTX, rv2["status"])
    check("食品行业 → 行业匹配仅 2 分", [p for p in s2["parts"] if p["维度"] == "行业匹配"][0]["得分"] == 2,
          s2["parts"][5]["依据"])
    s3 = score_job(dict(a, **{"JD 要点": "负责河南区域渠道开发，五险一金、补充医疗保险，要求5年以上家电经验。"}),
                   CTX, "verified")
    check("「补充医疗保险/五险一金」不误判为医疗行业",
          [p for p in s3["parts"] if p["维度"] == "行业匹配"][0]["得分"] == 10,
          s3["parts"][5]["依据"])
    check("行业判定函数：家电=True 食品=False 未知=False",
          industry_verdict("家电渠道")[1] and not industry_verdict("食品公司")[1]
          and industry_verdict("材料未见")[0] == "未知")

    s4 = score_job(dict(a, 风险标记="多平台重复发布，长期挂出"), CTX, "verified")
    check("刷量信号 → 扣 10 分并给原因",
          any(p["维度"] == "刷量降权" and p["得分"] == -10 for p in s4["parts"]) and bool(s4["reasons"]),
          "；".join(s4["reasons"]) or "无")
    s5 = score_job(dict(a), CTX, "verified", company_batch=3)
    check("同公司批量 3 条 → 扣 8 分",
          any(p["维度"] == "同公司批量降权" and p["得分"] == -8 for p in s5["parts"]),
          "；".join(s5["reasons"]))

    ctx_nosal = JobQueryContext(regions=["河南"], keywords=["区域经理"], industries=["家电"])
    s6 = score_job(dict(a, 薪资="8-9K"), ctx_nosal, "verified")
    s7 = score_job(dict(a, 薪资="8-9K"), JobQueryContext(regions=["河南"], keywords=["区域经理"],
                                                         industries=["家电"], salary_min=20000), "verified")
    check("薪资维度只读筛选器：不设筛选不扣分 / 设 20000 下限则 0 分",
          [p for p in s6["parts"] if p["维度"] == "薪资匹配"][0]["得分"] == 15
          and [p for p in s7["parts"] if p["维度"] == "薪资匹配"][0]["得分"] == 0,
          f"未设={[p for p in s6['parts'] if p['维度'] == '薪资匹配'][0]['得分']} / "
          f"设下限={[p for p in s7['parts'] if p['维度'] == '薪资匹配'][0]['得分']}")

    rv3 = classify(dict(a, 地区="全国"), CTX, material)
    check("「全国/不限」不得进目标区域池", rv3["status"] == "pending", rv3["reasons"][:1])
    for ph in ("JD 未覆盖", "JD未覆盖", "站内检索", "材料未覆盖", "待核实"):
        rph = classify(dict(a, **{"JD 要点": ph}), CTX, material)
        check(f"JD 占位变体「{ph}」→ pending", rph["status"] == "pending", rph["status"])
    rv4 = classify(dict(a, 岗位="区域经理岗"), CTX, material)
    check("正常写法「区域经理岗」不被过度拒绝", rv4["status"] == "verified", f"{rv4['status']} {rv4['reasons']}")

    report_v2 = """## 表一 · 今日具体岗位
| 岗位 | 公司 | 地区 | 薪资 | 来源平台 | 链接 | JD要点 |
|---|---|---|---|---|---|---|
| 渠道销售经理 | XX家电有限公司 | 郑州 | 12-18K | BOSS直聘 | https://www.zhipin.com/job_detail/x.html | 负责河南渠道开发与经销商维护，完成年度指标，要求三年以上经验 |

## 表二 · 待核实岗位
| 岗位 | 公司 | 地区 | 来源平台 | 链接 | 缺什么 |
|---|---|---|---|---|---|
| 行业新闻：家电以旧换新 | 材料未见 | — | 站内检索 | 官网 | 非岗位 |
| 渠道销售岗 | 美的集团 | 郑州 | 站内检索 | 公司招聘主页 | 缺岗位链接与JD |
"""
    rv5 = process_report(report_v2, CTX, material)
    check("表一真实岗位进池", rv5["stats"]["verified"] == 1, str(rv5["stats"]))
    check("表二里的情报类标题 → invalid（不倒进待核实）",
          all("行业新闻" not in (x.get("岗位") or "") for x in rv5["pending"]),
          "、".join(x.get("岗位", "") for x in rv5["pending"]))
    check("行上带扣分原因 _score_reasons", all("_score_reasons" in x for x in rv5["pool"]),
          str(rv5["pool"][0].get("_score_reasons")) if rv5["pool"] else "pool 为空")

    rows = [dict(a, 链接="https://www.zhipin.com/job_detail/v1.html"),
            dict(b, 链接="https://www.zhipin.com/job_detail/v2.html")]
    ver, pen = verify_jobs(rows, CTX, material)
    check("verify_jobs 兼容包装：返回 (verified, pending) 且写入 _score",
          len(ver) == 1 and len(pen) == 1 and all("_score" in r for r in ver + pen),
          f"verified={len(ver)} pending={len(pen)}")

    print(f"\n结果：{'全部通过' if ok_all else '存在失败项'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
