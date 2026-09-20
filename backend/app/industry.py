"""行业赛道研判引擎（生命周期五档：新势力 / 蓝海朝阳 / 平稳存量 / 红海内卷 / 夕阳没落）。

三层与背调同构，**先确定性、后模型**：
  ① 规则层（本文件）：行业级公开事实（增速/融资/政策/集中度/价格战/毛利/产能/招聘/薪资…）
     按权重算分 → 落到五档之一，并给出该档的进入时机、岗位选择、谈薪与避坑建议；
  ② 检索层（ai.py `_gather_search`）：8 路行业检索（规模增速 / 融资 / 价格战 / 产能 / 政策 / 集中度 / 招聘 / 区域产业基础）；
  ③ 词库层：从检索材料里数"阶段特征词"（价格战、去产能、渗透率、补贴退坡…）交叉验证规则层结论；
  ④ 模型层：写研判报告（五节），不得推翻规则层档位（档位是判定，模型负责解释与给动作）。

建议档位与个人画像挂钩：候选人若定位"成熟体系放大器"，则蓝海朝阳/平稳存量最优，
新势力需先确认融资节奏与现金流，红海需确认提成兑现与账期，夕阳原则上不进。
"""
import re
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------- 五档定义

STAGES: list[dict[str, Any]] = [
    {
        "id": "emerging",
        "name": "新势力 / 风口期",
        "badge": "风口",
        "min": 80,
        "features": "技术或政策驱动的新需求；格局未定；资本密集进入；标准与渠道都还没形成",
        "opportunity": "早期参与可拿股权/期权，能力稀缺溢价高，晋升快",
        "risk": "现金流不稳、融资断档即裁员；岗位常是「从零开荒且无资源」，半年换一拨人",
        "job_advice": "只在自己能验证的细分里进；先问三件事：账上现金够发几个月工资、本轮融资到账时间、这个岗位的前任去向",
        "entry_verdict": "可进，但要按风投标准来（小额、短周期、可撤出）",
    },
    {
        "id": "growth",
        "name": "蓝海朝阳（成长期）",
        "badge": "朝阳",
        "min": 65,
        "features": "需求快速增长、渗透率仍在抬升；玩家增加但格局初定；政策多为扶持；毛利尚可",
        "opportunity": "**体系搭建期**——渠道政策/区域架构/培训体系都还在建，区域负责人价值最大、谈判空间最大",
        "risk": "扩张过快导致管理粗放；补贴依赖；同质化苗头已现",
        "job_advice": "优先看「是否在按体系搭班子」：有没有渠道政策、返利规则、区域编制；谈薪时把提成规则与结算周期写进 offer",
        "entry_verdict": "最佳窗口：优先投递",
    },
    {
        "id": "mature",
        "name": "平稳存量（成熟期）",
        "badge": "存量",
        "min": 45,
        "features": "增速与 GDP/人口同步；龙头集中度较高；竞争靠份额与效率；以旧换新/更新替换为主需求",
        "opportunity": "体系成熟、现金流稳、五险一金规范；适合「成熟体系放大器」型选手放大操盘规模",
        "risk": "晋升通道拥挤、按资排辈；增量靠抢份额，指标压力逐年加码；创新岗位少",
        "job_advice": "**只进龙头或细分第一**（行业第二/第三在存量期最难受）；重点问：区域盘子多大、编制几人、考核是回款还是出货、近三年区域增长",
        "entry_verdict": "稳健选择：龙头优先，二线谨慎",
    },
    {
        "id": "saturated",
        "name": "红海内卷（饱和期）",
        "badge": "红海",
        "min": 25,
        "features": "增速低或负、玩家众多、价格战与同质化；毛利下滑；靠补贴或资本输血维持",
        "opportunity": "只剩效率与成本优势能赚钱；强者恒强，头部集中会加速",
        "risk": "压货与拖欠高发；提成规则常被单方面调整；区域负责人被打成「压货工具」；账期越来越长",
        "job_advice": "若必须进：只进头部且要求书面化提成与结算周期；**必须核实近一年提成实际兑现情况**（问在职/离职同事）；不要接「无体系开荒」岗",
        "entry_verdict": "谨慎：除非头部+条件书面化，否则不进",
    },
    {
        "id": "declining",
        "name": "夕阳没落（衰退期）",
        "badge": "夕阳",
        "min": 0,
        "features": "需求持续萎缩、政策限制或替代技术成熟；产能过剩、企业批量退出与关停",
        "opportunity": "少数垄断细分或转型成功的公司仍有稳定收益",
        "risk": "裁员与欠薪风险最高；社保断缴、补偿金拖欠常见；技能与行业一起贬值",
        "job_advice": "原则上不进；若已在其中，优先把能力迁移到相邻成长行业（渠道/客户资源可迁移），不要在衰退行业里赌晋升",
        "entry_verdict": "不建议：优先做行业迁移",
    },
]


def stage_of(score: float) -> dict[str, Any]:
    for st in STAGES:
        if score >= st["min"]:
            return st
    return STAGES[-1]


# ------------------------------------------------- 事实字段（前端表单契约）

# type: number 数字 / int 整数 / bool 是-否 / text 文本 / select 单选
INDUSTRY_FIELDS: list[dict[str, Any]] = [
    {"key": "demand_signal", "label": "需求信号", "type": "select", "essential": True,
     "options": ["爆发", "快速增长", "稳定", "放缓", "萎缩"], "help": "行业整体需求的方向"},
    {"key": "growth_rate", "label": "行业规模近 3 年复合增速（%）", "type": "number", "essential": True,
     "help": "如 12.5；负增长填负数"},
    {"key": "policy_stance", "label": "政策方向", "type": "select", "essential": True,
     "options": ["强扶持", "扶持", "中性", "限制", "强限制"]},
    {"key": "price_war", "label": "价格战 / 内卷程度", "type": "select", "essential": True,
     "options": ["无", "局部", "激烈", "恶性"]},
    {"key": "margin_trend", "label": "行业毛利率趋势", "type": "select", "essential": True,
     "options": ["上升", "持平", "下降", "大幅下降"]},
    {"key": "hiring_trend", "label": "招聘需求趋势", "type": "select", "essential": True,
     "options": ["大幅扩张", "扩张", "平稳", "收缩", "大幅收缩"]},
    {"key": "funding_events", "label": "近 12 个月融资/并购事件数", "type": "int", "essential": True},
    {"key": "player_change", "label": "玩家数量变化", "type": "select",
     "options": ["大量增加", "缓慢增加", "基本稳定", "开始减少", "大量退出"]},
    {"key": "cr5", "label": "前五企业市占率 CR5（%）", "type": "number", "help": "集中度；查不到可空"},
    {"key": "capacity", "label": "产能 / 供给", "type": "select",
     "options": ["严重不足", "偏紧", "基本平衡", "过剩", "严重过剩"]},
    {"key": "ipo_count", "label": "近 12 个月新增上市/过会企业数", "type": "int"},
    {"key": "salary_trend", "label": "薪资趋势", "type": "select", "options": ["上涨", "持平", "下降"]},
    {"key": "tech_disruption", "label": "技术/替代品威胁", "type": "select", "options": ["弱", "中", "强"]},
    {"key": "export_trend", "label": "出口/出海", "type": "select", "options": ["高增长", "平稳", "下滑"]},
    {"key": "subsidy_dependency", "label": "依赖补贴或资本输血", "type": "bool"},
    {"key": "key_policy", "label": "关键政策/规划文件", "type": "text",
     "help": "如《推动大规模设备更新和消费品以旧换新行动方案》"},
    {"key": "region_fit", "label": "当地产业基础（区域适配）", "type": "select", "options": ["强", "中", "弱"]},
]


class IndustryFacts(BaseModel):
    industry: str = ""
    region: str = ""
    demand_signal: Optional[str] = None
    growth_rate: Optional[float] = None
    policy_stance: Optional[str] = None
    price_war: Optional[str] = None
    margin_trend: Optional[str] = None
    hiring_trend: Optional[str] = None
    funding_events: Optional[int] = None
    player_change: Optional[str] = None
    cr5: Optional[float] = None
    capacity: Optional[str] = None
    ipo_count: Optional[int] = None
    salary_trend: Optional[str] = None
    tech_disruption: Optional[str] = None
    export_trend: Optional[str] = None
    subsidy_dependency: Optional[bool] = None
    key_policy: Optional[str] = None
    region_fit: Optional[str] = None


# ---------------------------------------------------------------- 规则表

# (字段, 权重, 取值映射；growth_rate 用数字区间单独处理)
SELECT_RULES: list[tuple[str, int, dict[str, float]]] = [
    ("demand_signal", 25, {"爆发": 1.0, "快速增长": 0.85, "稳定": 0.55, "放缓": 0.3, "萎缩": 0.05}),
    ("policy_stance", 12, {"强扶持": 1.0, "扶持": 0.8, "中性": 0.55, "限制": 0.25, "强限制": 0.05}),
    ("price_war", 12, {"无": 1.0, "局部": 0.7, "激烈": 0.35, "恶性": 0.1}),
    ("margin_trend", 10, {"上升": 1.0, "持平": 0.6, "下降": 0.3, "大幅下降": 0.1}),
    ("capacity", 6, {"严重不足": 0.9, "偏紧": 0.85, "基本平衡": 0.6, "过剩": 0.3, "严重过剩": 0.1}),
    ("player_change", 6, {"大量增加": 0.9, "缓慢增加": 0.75, "基本稳定": 0.55, "开始减少": 0.4, "大量退出": 0.15}),
    ("hiring_trend", 6, {"大幅扩张": 1.0, "扩张": 0.85, "平稳": 0.55, "收缩": 0.3, "大幅收缩": 0.1}),
    ("salary_trend", 4, {"上涨": 0.9, "持平": 0.6, "下降": 0.3}),
    ("tech_disruption", 4, {"弱": 0.8, "中": 0.6, "强": 0.35}),
    ("export_trend", 4, {"高增长": 0.9, "平稳": 0.6, "下滑": 0.3}),
    ("region_fit", 4, {"强": 0.85, "中": 0.6, "弱": 0.35}),
]

FACTOR_LABEL = {
    "demand_signal": "需求信号", "policy_stance": "政策方向", "price_war": "价格战程度",
    "margin_trend": "毛利率趋势", "capacity": "产能供需", "player_change": "玩家数量变化",
    "hiring_trend": "招聘需求趋势", "salary_trend": "薪资趋势", "tech_disruption": "技术替代威胁",
    "export_trend": "出口/出海", "region_fit": "当地产业基础", "growth_rate": "行业规模增速",
    "funding_events": "融资活跃度", "ipo_count": "上市/过会活跃度", "subsidy_dependency": "补贴/资本依赖",
    "cr5": "集中度 CR5", "key_policy": "关键政策",
}


def _num_score(key: str, v: float) -> float:
    if key == "growth_rate":
        if v >= 30:
            return 1.0
        if v >= 15:
            return 0.85
        if v >= 5:
            return 0.6
        if v >= 0:
            return 0.45
        return 0.1
    return 0.5


def _count_score(key: str, v: float) -> float:
    if key == "funding_events":
        if v >= 20:
            return 1.0
        if v >= 10:
            return 0.85
        if v >= 5:
            return 0.7
        if v >= 1:
            return 0.5
        return 0.35
    if key == "ipo_count":
        if v >= 5:
            return 1.0
        if v >= 1:
            return 0.75
        return 0.5
    return 0.5


def evaluate(facts: "IndustryFacts | dict[str, Any]") -> dict[str, Any]:
    """按规则算分并落到五档之一；纯函数：同输入同输出。"""
    d: dict[str, Any] = facts.model_dump() if isinstance(facts, IndustryFacts) else dict(facts)
    name = (d.get("industry") or "").strip() or "该行业"
    region = (d.get("region") or "").strip()

    total_w = 0.0
    acc = 0.0
    factors: list[dict[str, Any]] = []
    missing: list[str] = []

    for field, w, mapping in SELECT_RULES:
        v = d.get(field)
        if v is None or v == "":
            if field in ("demand_signal", "policy_stance", "price_war", "margin_trend", "hiring_trend"):
                missing.append(FACTOR_LABEL[field])
            continue
        s = mapping.get(str(v))
        if s is None:
            continue
        total_w += w
        acc += w * s
        factors.append({"field": field, "label": FACTOR_LABEL[field], "value": v, "points": round(s, 2), "weight": w})

    if d.get("growth_rate") is not None:
        s = _num_score("growth_rate", float(d["growth_rate"]))
        total_w += 15
        acc += 15 * s
        factors.append({"field": "growth_rate", "label": "行业规模增速", "value": f"{d['growth_rate']}%", "points": s, "weight": 15})
    else:
        missing.append("行业规模增速")

    if d.get("funding_events") is not None:
        s = _count_score("funding_events", float(d["funding_events"]))
        total_w += 10
        acc += 10 * s
        factors.append({"field": "funding_events", "label": "融资活跃度", "value": d["funding_events"], "points": s, "weight": 10})
    else:
        missing.append("融资/并购事件数")

    if d.get("ipo_count") is not None:
        s = _count_score("ipo_count", float(d["ipo_count"]))
        total_w += 5
        acc += 5 * s
        factors.append({"field": "ipo_count", "label": "上市/过会活跃度", "value": d["ipo_count"], "points": s, "weight": 5})

    if d.get("subsidy_dependency") is not None:
        s = 0.3 if d["subsidy_dependency"] else 0.9
        total_w += 5
        acc += 5 * s
        factors.append({"field": "subsidy_dependency", "label": "补贴/资本依赖",
                        "value": "是" if d["subsidy_dependency"] else "否", "points": s, "weight": 5})

    score = round(acc / total_w * 100, 1) if total_w else 0.0

    # ---- 新势力门槛（风口不是"增长快"，而是"需求被新东西激发"）----
    # 只有满足以下之一才算新势力/风口期，否则即使分数很高也压回「蓝海朝阳」：
    #   a) 需求爆发；b) 增速 ≥30% 且近 12 个月融资 ≥15 起；c) 玩家大量增加 + 需求爆发
    growth_v = float(d["growth_rate"]) if d.get("growth_rate") is not None else None
    funding_v = int(d["funding_events"]) if d.get("funding_events") is not None else 0
    emerging_gate = (
        d.get("demand_signal") == "爆发"
        or (growth_v is not None and growth_v >= 30 and funding_v >= 15)
        or (d.get("player_change") == "大量增加" and d.get("demand_signal") == "爆发")
    )
    gates: list[str] = []
    if score >= 80 and not emerging_gate:
        score = min(score, 79)
        gates.append("未满足新势力门槛（需求爆发 / 增速≥30% 且融资≥15 起）→ 档位上限「蓝海朝阳」")

    # ---- 硬性上限（口径一致、可解释）----
    caps: list[str] = []
    if d.get("policy_stance") == "强限制":
        score = min(score, 44)
        caps.append("政策强限制 → 档位上限「红海内卷」")
    if d.get("price_war") == "恶性" and d.get("margin_trend") in ("下降", "大幅下降"):
        score = min(score, 44)
        caps.append("恶性价格战 + 毛利下滑 → 档位上限「红海内卷」")
    if d.get("capacity") in ("过剩", "严重过剩") and d.get("demand_signal") in ("放缓", "萎缩"):
        score = min(score, 44)
        caps.append("产能过剩 + 需求放缓 → 档位上限「红海内卷」")
    if d.get("demand_signal") == "萎缩" and (growth_v is None or growth_v < 0):
        score = min(score, 24)
        caps.append("需求萎缩且规模负增长 → 档位上限「夕阳没落」")
    if d.get("demand_signal") in ("放缓", "萎缩") and d.get("hiring_trend") in ("收缩", "大幅收缩"):
        score = min(score, 64)
        caps.append("需求放缓 + 招聘收缩 → 档位上限「平稳存量」（不再按成长期给建议）")

    st = stage_of(score)
    pos = [f for f in factors if f["points"] >= 0.75]
    neg = [f for f in factors if f["points"] <= 0.4]
    order = {"emerging": 0, "growth": 1, "mature": 2, "saturated": 3, "declining": 4}
    all_ids = [s["id"] for s in STAGES]
    idx = all_ids.index(st["id"])
    neighbors = [s for s in STAGES[max(0, idx - 1): idx + 2] if s["id"] != st["id"]]
    confidence = round(min(1.0, total_w / 110.0), 2)

    return {
        "ok": True,
        "industry": name,
        "region": region,
        "score": score,
        "stage": st,
        "stage_order": order[st["id"]],
        "factors": sorted(factors, key=lambda f: -f["points"]),
        "positive": [f"{f['label']}={f['value']}" for f in pos],
        "negative": [f"{f['label']}={f['value']}" for f in neg],
        "caps": caps,
        "gates": gates,
        "emerging_gate": emerging_gate,
        "missing": missing,
        "confidence": confidence,
        "neighbors": [{"id": s["id"], "name": s["name"], "badge": s["badge"]} for s in neighbors],
    }


# ------------------------------------------------- 阶段特征词库（交叉验证）

STAGE_KEYWORDS: dict[str, list[str]] = {
    "emerging": ["元年", "爆发", "颠覆", "首发", "首次量产", "试点", "独角兽", "新赛道", "资本追捧", "从 0 到 1", "技术突破", "风口"],
    "growth": ["快速增长", "渗透率提升", "政策扶持", "补贴", "扩容", "需求旺盛", "供不应求", "涨价", "扩产", "高增长", "抢跑"],
    "mature": ["存量", "以旧换新", "更新换代", "稳定增长", "成熟期", "份额", "龙头集中", "微增", "替换需求"],
    "saturated": ["价格战", "内卷", "杀价", "降价", "同质化", "亏损", "补贴退坡", "产能过剩", "库存高企", "价格倒挂", "血亏"],
    "declining": ["需求萎缩", "退出", "关停", "去产能", "限制", "下滑", "转型", "裁员", "停产", "衰退"],
}


def scan_stage(text: str) -> dict[str, Any]:
    """从检索材料里数各阶段特征词，用于交叉验证规则层档位。

    两个必须做的校正（否则会自我误导）：
    ① **剔除检索式回显**：材料块以「【检索 i】查询词」开头，检索词本身含「价格战/内卷」这类词，
       不剔除就会把自己的提问算成行业特征；
    ② **按键词数归一**：各档关键词条数不同，用「每词平均命中」比较才公平（原始计数同时保留）。
    """
    if not text:
        return {"counts": {}, "avg": {}, "dominant": "", "hits": [], "per1000": {}}
    body = "\n".join(ln for ln in text.splitlines() if not re.match(r"^\s*【检索\s*\d+】", ln))
    counts: dict[str, int] = {}
    hits: list[dict[str, Any]] = []
    low = body.lower()
    for sid, kws in STAGE_KEYWORDS.items():
        n = 0
        for kw in kws:
            c = low.count(kw.lower())
            if c:
                n += c
                hits.append({"stage": sid, "keyword": kw, "count": c})
        counts[sid] = n
    avg = {sid: round(counts[sid] / max(len(STAGE_KEYWORDS[sid]), 1), 2) for sid in STAGE_KEYWORDS}
    chars = max(len(body), 1)
    per1000 = {sid: round(counts[sid] / chars * 1000, 2) for sid in STAGE_KEYWORDS}
    dominant = max(avg, key=lambda k: avg[k]) if avg and max(avg.values()) > 0 else ""
    hits.sort(key=lambda h: -h["count"])
    return {"counts": counts, "avg": avg, "per1000": per1000, "dominant": dominant, "hits": hits[:20], "chars": chars}


def industry_queries(industry: str, region: str = "") -> list[str]:
    """行业研判检索路（8 路）：规模增速 / 融资 / 价格战 / 产能 / 政策 / 集中度 / 招聘 / 区域产业基础。"""
    ind = (industry or "").strip() or "家电"
    rg = (region or "").strip() or "河南"
    return [
        f"{ind} 行业 市场规模 增速 报告",
        f"{ind} 行业 融资 事件 投资 2025",
        f"{ind} 价格战 内卷 降价 毛利率",
        f"{ind} 产能过剩 供大于求 库存",
        f"{ind} 政策 规划 支持 限制 标准",
        f"{ind} 行业 龙头 市占率 集中度 CR5",
        f"{ind} 招聘 人才 需求 薪资 趋势",
        f"{rg} {ind} 产业 集群 基础 配套",
    ]


# ---------------------------------------------------------------- 接口

class IndustryRequest(BaseModel):
    industry: str = ""
    region: str = ""
    facts: dict[str, Any] = {}


@router.get("/industry/framework")
def industry_framework():
    """五档定义 + 事实字段元数据 + 阶段特征词库（前端据此生成表单与说明）。"""
    return {
        "ok": True,
        "stages": STAGES,
        "fields": INDUSTRY_FIELDS,
        "keywords": STAGE_KEYWORDS,
        "weights": [{"field": f, "weight": w} for f, w, _ in SELECT_RULES]
        + [{"field": "growth_rate", "weight": 15}, {"field": "funding_events", "weight": 10},
           {"field": "ipo_count", "weight": 5}, {"field": "subsidy_dependency", "weight": 5}],
    }


@router.post("/industry/evaluate")
def industry_evaluate(req: IndustryRequest):
    """规则层研判：同输入同输出，不调用模型、秒回。"""
    merged = {"industry": req.industry, "region": req.region, **req.facts}
    return evaluate(merged)


@router.get("/industry/checklist")
def industry_checklist(industry: str = "", region: str = ""):
    """核查清单：检索关键词 + 每档判据（便于人工核验原始报告）。"""
    return {
        "ok": True,
        "industry": industry,
        "region": region,
        "queries": industry_queries(industry, region),
        "criteria": [
            {"stage": s["name"], "features": s["features"], "min": s["min"], "verdict": s["entry_verdict"]}
            for s in STAGES
        ],
    }
