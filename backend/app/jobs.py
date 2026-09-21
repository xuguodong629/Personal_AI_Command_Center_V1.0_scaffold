"""岗位真实性判定与岗位评分 V2.0（岗位雷达专用；独立于 LLM 的确定性规则层）。

**要解决的问题**：早期 `_extract_pool_rows()` 只检查「岗位不为空、公司不为空」，于是
「渠道/区域销售岗（JD 未覆盖，站内检索）」「公司招聘入口」「美的集团」（公司级情报）、
「公司正在扩产 → 推测要招区域经理」这类内容全部被当成具体岗位塞进机会池，并且把**公司综合评分**
当成岗位评分挂在上面。

**立场（原则 1）**：宁可 0 个岗位，绝不用公司情报凑岗位。

三层确定性规则：
  ① 硬门槛（7 项）：岗位名 / 公司 / 地区 / JD 要点 / 来源平台 / 链接 / 地区匹配
     → 全过 = `verified`（进具体岗位池）；缺项 = `pending`（进待核实）；情报/入口类 = `invalid`（排除）
  ② 链接与引用核验：链接必须是真实 URL 或**引用编号在检索材料里真实存在**（可识别编造的 [9.9]）；
     公司主页 / 招聘入口链接（careers / companydetail / campus / socialhome…）一律不算岗位链接
  ③ 岗位评分（0–100，与公司评分彻底分离）：岗位真实性 30 / 地区匹配 15 / 岗位匹配 15 / 薪资匹配 15 /
     经验匹配 10 / 行业匹配 10 / 信息完整度 5，外加**刷量降权**与**同公司批量降权**

V2.0 变更（在 V1 基础上）
  ✅ 公司主页 / 招聘入口 URL 黑名单 → 判 pending（不再混进具体岗位池）
  ✅ 行业白/黑名单 `industry_verdict()`（家电厨电为白；食品医疗地产金融教培为黑），带假阳性保护
  ✅ 刷量降权：长期挂出 / 多平台重复 / 猎头代招 / 派遣 / 中介 −10；同公司本批 ≥3 条 −8
  ✅ `_score_reasons`（扣分原因）随行返回，前端可直接展示
  ✅ 扩充岗位名 deny 词（招聘专区 / 加入我们 / 全部职位 / 职位列表 / 热门职位 / 职位汇总 / 校招首页…）
  ✅ ROLE_WORDS 取并集（督导 / 运营 / 市场 / 采购 / 财务 / 人事 / 技术 / 产品 / 设计 / 安装 / 售后 / 导购 / 省区 / 片区…）
  ✅ 薪资**只读筛选器** `salary_min/max`，绝不读简历摘要

⚠️ 与中途那份"V2.0 补丁"的差异（那份若整段覆盖会当场跑挂，这里逐条修正）
  1. `classify()` 缺失 → `process_report()` 会 NameError；本文件补齐，且**判定逻辑只有这一处**
  2. `parse_salary()` 引用了不存在的 `SALARY_RE` → NameError；本文件统一正则命名并保留旧名别名
  3. `score_job()` 里 `want_lo` 只在薪资筛选器非空时赋值 → 未设薪资筛选时报 UnboundLocalError；
     本文件先无条件算 `want_lo/want_hi`
  4. `region_verdict()` 返回顺序反了，且对「全国/不限」返回命中 → 全国岗位直接进池；
     本文件全文件统一 **(地区是否明确, 是否命中目标区域, 原因)**，且全国/不限/多地判"不具体"
  5. `is_placeholder()` 被收窄到 8 个词 → 漏掉「JD 未覆盖」「材料未覆盖」「站内检索」「待核实」；
     本文件恢复完整占位词表（会放过"站内检索充当 JD"的漏洞正是从这里来的）
  6. `DENY_TITLE_SUBSTR` 丢掉情报词（行业/新闻/政策/融资/扩产/上市/相关岗位/岗位需求/人才需求）→
     「区域销售岗位需求」「家电行业销售人才需求增加」会因含 ROLE_WORD「销售」被判成真实岗位
  7. `BAD_INDUSTRIES` 含「材料」→ 任何写着「材料未见」的行都被判行业不符；本文件剔除并加占位词预清洗
  8. `verify_jobs()` 是第二条并行判定路径，而 ai.py 从不调用它（等于规则没生效）；
     本文件只有 `process_report()` 一条路径，`verify_jobs()` 仅作兼容包装
"""
from __future__ import annotations

import re
from typing import Any

# ==========================================================
# 一、词表
# ==========================================================

# ---- 占位 / 无信息（完整词表；收窄会直接放过"站内检索""JD 未覆盖"）----
PLACEHOLDER_EXACT = {
    "—", "-", "--", "/", "无", "暂无", "不详", "未知", "空", "none", "n/a", "na", "null",
    "招聘入口", "职位列表", "全部职位", "热门职位", "岗位列表", "职位汇总",
}
PLACEHOLDER_SUBSTR = (
    "材料未见", "材料未覆盖", "材料未公开", "未覆盖", "未找到", "未公开", "信息不足", "待核实", "待确认",
    "无法确认", "不明确", "未标注", "未提及", "未提供", "站内检索", "招聘入口", "需站内", "无法判断",
    "jd未覆盖", "jd 未覆盖", "暂无数据", "缺失", "未返回", "引擎未返回",
)

# ---- 行业白名单（目标行业）----
GOOD_INDUSTRIES = (
    "家电", "厨电", "中央空调", "暖通", "消费电子", "智能家居", "智能硬件", "小家电",
    "热水器", "净水", "卫浴电器", "照明电器", "空调", "电器", "白电", "黑电", "3c", "家居",
)

# ---- 行业黑名单（一票降权，不是硬门槛）----
BAD_INDUSTRIES = (
    "食品", "餐饮", "医疗", "医院", "医药", "保险", "证券", "银行", "基金", "金融",
    "房地产", "地产", "物业", "农业", "种业", "养殖", "化工", "煤矿", "建筑",
    "法律咨询", "教育培训", "教培", "直播带货", "主播", "mcn", "网贷", "小贷",
)
# 行业判定的假阳性保护：这些语境里的「医疗/银行/保险/物业」不是行业
INDUSTRY_FALSE_POSITIVE = (
    "补充医疗", "医疗保险", "医疗险", "五险一金", "社会保险", "商业保险", "公积金",
    "银行流水", "银行回单", "开户银行", "银行账户", "保险起见", "物业费", "物业管理费",
)

# ---- 岗位名必须包含的「具体职位词」（V1 ∪ V2 并集）----
ROLE_WORDS = (
    "区域经理", "大区经理", "城市经理", "渠道经理", "渠道主管", "销售经理", "业务经理",
    "招商主管", "ka经理", "省区经理", "销售代表", "客户经理", "营销经理", "业务代表",
    "经理", "主管", "总监", "代表", "专员", "顾问", "工程师", "店长", "督导", "负责人", "主任",
    "助理", "销售", "渠道", "客户", "区域", "大区", "城市", "省区", "片区",
    "运营", "市场", "采购", "财务", "人事", "hr", "bd", "技术", "产品", "设计",
    "安装", "售后", "导购",
)

# ---- 明显不是岗位：情报 / 入口 / 泛指 / 校招 ----
DENY_TITLE_SUBSTR = (
    # 招聘入口 / 页面类
    "招聘入口", "招聘主页", "招聘页", "招聘公告", "招聘启事", "招聘信息", "招聘专栏", "招聘汇总",
    "招聘专区", "全部职位", "职位列表", "岗位列表", "岗位列表", "职位汇总", "热门职位", "岗位合集",
    "查看更多职位", "加入我们", "工作在", "社会招聘首页", "校招首页", "公司主页", "官方招聘",
    "官网招聘", "公司官网", "careers", "socialhome",
    # 泛指 / 推测类
    "相关岗位", "相关职位", "多个岗位", "若干岗位", "岗位类别", "岗位方向", "岗位名称", "类似岗位",
    "等岗位", "类岗位", "岗位需求", "人才需求", "人才储备", "人才池", "储备", "未覆盖", "待核实",
    "可能有", "预计招聘", "或将招聘", "招聘计划",
    # 情报 / 新闻 / 政策 / 资本（去掉这些 → 含"销售"的情报标题会漏网）
    "行业", "新闻", "资讯", "情报", "政策", "规划", "融资", "扩产", "投产", "上市", "并购",
    "中标", "专精特新", "专利", "汇总",
    # 校招 / 届别（社招场景排除）
    "校园招聘", "校招", "应届", "实习生招聘", "双选会", "宣讲会",
)
# 表二（待核实）里若命中这些词 → 判为情报而非岗位（避免模型把新闻倒进待核实）
INFO_TITLE_SUBSTR = (
    "行业", "新闻", "资讯", "情报", "政策", "规划", "融资", "扩产", "投产", "上市", "并购", "中标",
    "专精特新", "专利", "汇总", "校园招聘", "校招", "应届", "宣讲会", "双选会",
    "招聘入口", "招聘主页", "全部职位", "职位列表", "热门职位", "加入我们", "公司主页", "careers",
)
GENERIC_TAIL = ("岗位", "方向", "类别", "销售岗", "渠道岗", "区域销售岗", "职位", "类岗位", "职位类")

# ---- 公司主页 / 招聘入口 URL 特征（这类链接不能当岗位链接）----
HOMEPAGE_URL_PATTERNS = (
    "companydetail", "company/", "companys/", "socialhome", "careers", "campus",
    "jobs-worldwide", "joinus", "join-us", "zhaopin/", "/gongsi/",
)

# ---- 来源平台白名单 ----
PLATFORM_OK_SUBSTR = (
    "boss", "直聘", "猎聘", "智联", "前程无忧", "51job", "linkedin", "领英", "脉脉",
    "官网", "官方招聘", "公司招聘", "公众号", "招聘网", "人才网", "人才市场", "人社局", "人社",
    "政府", "公共招聘", "猎头", "内推", "中华英才", "58同城", "赶集",
)
# ---- JD 要点的"像 JD"信号词 ----
JD_SIGNALS = (
    "职责", "负责", "要求", "任职", "经验", "学历", "熟悉", "能力", "沟通", "维护", "开发", "拓展",
    "完成", "管理", "指标", "回款", "渠道", "客户", "团队", "考核", "年限", "专业", "优先",
)
COMPANY_DENY_SUBSTR = ("材料未见", "未公开", "未找到", "多个公司", "若干公司", "相关公司", "等公司",
                       "同行业", "该行业", "目标行业", "未知", "待核实", "不详")

# ---- 刷量 / 虚假招聘信号（只看风险列与时间列，不扫 JD，避免"外包管理"这类误伤）----
VOLUME_SIGNALS = ("长期挂出", "长期有效", "常年招聘", "多平台重复", "批量发布", "批量挂岗",
                  "猎头代招", "中介", "派遣", "外包", "重复发布", "暂满", "储备人才")

# ==========================================================
# 二、正则
# ==========================================================

CITATION_RE = re.compile(r"\[(\d+(?:\.\d+)?)\]")
URL_RE = re.compile(r"https?://[^\s)\]，。；]+")

SALARY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—]\s*(\d+(?:\.\d+)?)\s*[kK]")
SALARY_ONE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[kK]")
SALARY_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—]\s*(\d+(?:\.\d+)?)\s*万")
# 旧名别名（避免其他地方 import 报错）
SALARY_K_RE = SALARY_RE
SALARY_ONE_K_RE = SALARY_ONE_RE

EXP_RANGE_RE = re.compile(r"(\d+)\s*[-~—]\s*(\d+)\s*年")
EXP_PLUS_RE = re.compile(r"(\d+)\s*年以上")
EXP_ONE_RE = re.compile(r"(\d+)\s*年")


# ==========================================================
# 三、Context
# ==========================================================


class JobQueryContext:
    """Radar 检索上下文。

    注意：只有**筛选器**里的 `salary_min/salary_max`、`regions/keywords/industries`、`exp_years`
    参与判定与评分；简历摘要不参与（简历只影响职位匹配的表述，不影响薪资门槛）。
    """

    def __init__(
        self,
        regions: list[str],
        keywords: list[str],
        industries: list[str],
        salary_min: int = 0,
        salary_max: int = 0,
        exp_years: str = "any",
        job_type: str = "any",
        social_recruit: bool = True,
    ) -> None:
        self.regions = [x.strip() for x in (regions or []) if x and x.strip()]
        self.keywords = [x.strip() for x in (keywords or []) if x and x.strip()]
        self.industries = [x.strip() for x in (industries or []) if x and x.strip()]
        self.salary_min = salary_min or 0
        self.salary_max = salary_max or 0
        self.exp_years = exp_years or "any"
        self.job_type = job_type or "any"
        self.social_recruit = social_recruit


# ==========================================================
# 四、通用工具
# ==========================================================


def _cell(row: dict, *names: str) -> str:
    """按列名取值：先精确匹配，再子串匹配（兼容「JD要点 / JD 要点」「经验 / 经验/学历要求」）。"""
    keys = [k for k in row.keys() if isinstance(k, str)]
    for name in names:
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
    for name in names:
        low = name.lower()
        for k in keys:
            if low in k.lower() and row.get(k) not in (None, ""):
                return str(row[k]).strip()
    return ""


def is_placeholder(value: str) -> bool:
    """字段是否为占位 / 无信息（完整词表，勿收窄）。"""
    v = (value or "").strip()
    if not v:
        return True
    low = v.lower()
    if low in PLACEHOLDER_EXACT:
        return True
    return any(t in low for t in PLACEHOLDER_SUBSTR)


# ==========================================================
# 五、硬门槛判定
# ==========================================================


def title_verdict(title: str, ctx: JobQueryContext) -> tuple[bool, str]:
    """岗位名是否是可核验的具体职位。"""
    t = (title or "").strip()
    if is_placeholder(t):
        return False, "岗位名缺失"
    low = t.lower()
    for deny in DENY_TITLE_SUBSTR:
        if deny in low:
            if deny in ("校招", "校园招聘", "应届", "实习生招聘", "双选会", "宣讲会") and not ctx.social_recruit:
                return False, f"校招/应届岗位（{deny}）"
            return False, f"非具体岗位（含「{deny}」）"
    if re.search(r"(岗|职位|岗位)$", t) and not any(w in low for w in ROLE_WORDS):
        return False, "泛指岗位名（以「岗/岗位」结尾且无具体职位词）"
    if t.endswith(GENERIC_TAIL) and not any(w in low for w in ("经理", "主管", "总监", "专员", "代表", "顾问")):
        return False, "泛指岗位名（以方向/类别结尾）"
    if len(t) > 40:
        return False, "岗位标题异常（过长，像描述而非职位）"
    if not any(w in low for w in ROLE_WORDS):
        return False, "不像真实职位名（无职位词）"
    return True, ""


def company_verdict(company: str) -> tuple[bool, str]:
    c = (company or "").strip().strip("/")
    if is_placeholder(c):
        return False, "公司名缺失"
    low = c.lower()
    for deny in COMPANY_DENY_SUBSTR:
        if deny in low:
            return False, f"公司名不具体（含「{deny}」）"
    if len(c) < 2:
        return False, "公司名过短"
    return True, ""


def region_verdict(region: str, ctx: JobQueryContext) -> tuple[bool, bool, str]:
    """返回 **(地区是否明确, 是否命中目标区域, 原因)** —— 全文件唯一约定，勿改顺序。

    注：旧补丁对「全国/不限」返回命中，等于全国岗位直接进目标区域池，这里判为"不具体"。
    """
    r = (region or "").strip()
    if is_placeholder(r):
        return False, False, "工作地点缺失"
    if re.search(r"(全国|不限|多地|若干|多个城市|待定|面议)", r):
        return False, False, "工作地点不具体（全国/不限/多地）"
    if not re.search(r"[\u4e00-\u9fff]{2,}", r):
        return False, False, "工作地点不具体"
    if ctx.regions:
        for u in ctx.regions:
            if u and (u in r or r in u):
                return True, True, f"命中地区：{u}"
        # 放宽：用户填「河南」时，行内写省内 18 地市也算命中
        if any(u in ("河南", "河南省") for u in ctx.regions):
            henan = ("郑州", "洛阳", "开封", "南阳", "新乡", "安阳", "许昌", "平顶山", "信阳", "商丘",
                     "周口", "驻马店", "焦作", "濮阳", "漯河", "三门峡", "鹤壁", "济源", "新密")
            if any(c in r for c in henan):
                return True, True, "河南省内地市"
        return True, False, f"工作地点不在目标区域（{r}）"
    return True, True, r


def jd_verdict(jd: str) -> tuple[bool, str]:
    j = (jd or "").strip()
    if is_placeholder(j):
        return False, "JD 要点缺失"
    if len(j) < 24:
        return False, "JD 要点过短（<24 字）"
    low = j.lower()
    if not any(s in low for s in JD_SIGNALS):
        return False, "JD 要点不像岗位职责/要求"
    return True, ""


def platform_verdict(platform: str) -> tuple[bool, str]:
    p = (platform or "").strip()
    if is_placeholder(p):
        return False, "来源平台缺失"
    low = p.lower()
    if any(x in low for x in ("站内检索", "招聘入口", "材料未见", "未公开")):
        return False, "来源不是招聘平台（站内检索/入口）"
    if not any(x in low for x in PLATFORM_OK_SUBSTR):
        return False, f"来源平台无法识别（{p[:16]}）"
    return True, ""


def is_homepage_url(link: str) -> bool:
    """是否公司主页 / 招聘入口类链接（这类链接不能当岗位链接）。"""
    low = (link or "").lower()
    return any(p in low for p in HOMEPAGE_URL_PATTERNS)


def link_verdict(link: str, material: str) -> tuple[bool, str]:
    """链接必须是真实 URL，或**引用编号在检索材料里真实存在**（防编造 [9.9]）。"""
    l = (link or "").strip()
    if is_placeholder(l):
        return False, "链接缺失"
    if is_homepage_url(l):
        return False, "公司主页/招聘入口链接（非岗位链接）"
    if URL_RE.search(l):
        return True, ""
    cites = CITATION_RE.findall(l)
    if cites and material:
        if any(f"[{c}]" in material for c in cites):
            return True, ""
        return False, "引用编号在材料中不存在（疑似编造）"
    if cites:
        return False, "仅有引用编号但无材料可核验"
    return False, "无原始招聘链接"


def industry_verdict(text: str) -> tuple[str, bool]:
    """行业判定：命中白名单 → (词, True)；命中黑名单 → (词, False)；否则 ("未知", False)。

    假阳性保护：先剔除占位词与「补充医疗/五险一金/银行流水/物业费」等福利合规语境再判定
    （否则「材料未见」会被当成行业「材料」、「补充医疗保险」会把家电岗位判成医疗）。
    """
    s = (text or "").lower()
    for noise in INDUSTRY_FALSE_POSITIVE + PLACEHOLDER_SUBSTR + tuple(PLACEHOLDER_EXACT):
        if noise and noise in s:
            s = s.replace(noise, " ")
    for g in GOOD_INDUSTRIES:
        if g in s:
            return g, True
    for b in BAD_INDUSTRIES:
        if b in s:
            return b, False
    return "未知", False


# 兼容旧名（若别处引用）
TARGET_INDUSTRIES = set(GOOD_INDUSTRIES)


def detect_industry(row: dict) -> tuple[str, bool]:
    """兼容旧接口：从行里拼文本判行业。"""
    text = " ".join([_cell(row, "公司"), _cell(row, "岗位"), _cell(row, "JD")])
    return industry_verdict(text)


# ==========================================================
# 六、判定主流程（唯一路径）
# ==========================================================


def classify(row: dict, ctx: JobQueryContext, material: str = "") -> dict:
    """对一条候选记录做真实性判定。

    status: verified（进具体岗位池）/ pending（待核实）/ invalid（排除）
    """
    title = _cell(row, "岗位", "职位")
    company = _cell(row, "公司")
    region = _cell(row, "地区", "工作地点")
    jd = _cell(row, "JD", "职责")
    platform = _cell(row, "来源平台", "平台")
    link = _cell(row, "链接", "link", "url")

    t_ok, t_why = title_verdict(title, ctx)
    c_ok, c_why = company_verdict(company)
    r_ok, r_match, r_why = region_verdict(region, ctx)
    j_ok, j_why = jd_verdict(jd)
    p_ok, p_why = platform_verdict(platform)
    l_ok, l_why = link_verdict(link, material)

    gates = {
        "岗位": t_ok, "公司": c_ok, "地区": r_ok, "地区匹配": r_match,
        "JD要点": j_ok, "来源平台": p_ok, "链接": l_ok,
    }
    reasons = [w for w in (t_why, c_why, j_why, p_why, l_why) if w]
    # 地区只在"未通过"时才写进原因；命中的地区是正向信息，不该出现在「缺什么/未进池原因」里
    if r_why and not (r_ok and r_match):
        reasons.append(r_why)

    if not t_ok or not c_ok:
        status = "invalid"
    elif all(gates.values()):
        status = "verified"
    else:
        status = "pending"

    return {"status": status, "reasons": reasons, "gates": gates,
            "fields": {"title": title, "company": company, "region": region, "jd": jd,
                       "platform": platform, "link": link}}


def is_intel_title(title: str) -> bool:
    """是否情报/入口类标题（用于表二路由：模型把新闻倒进待核实时不至于当成岗位）。"""
    low = (title or "").lower()
    return any(x in low for x in INFO_TITLE_SUBSTR)


# ==========================================================
# 七、评分
# ==========================================================


def parse_salary(text: str) -> tuple[int, int]:
    """返回月薪区间（元）。(0,0) 表示无法解析。只处理传入文本。"""
    s = text or ""
    m = SALARY_RE.search(s)
    if m:
        return int(float(m.group(1)) * 1000), int(float(m.group(2)) * 1000)
    m = SALARY_WAN_RE.search(s)
    if m:
        lo, hi = float(m.group(1)) * 10000, float(m.group(2)) * 10000
        if "年薪" in s or "年包" in s:
            return int(lo / 12), int(hi / 12)
        return int(lo), int(hi)
    m = SALARY_ONE_RE.search(s)
    if m:
        v = int(float(m.group(1)) * 1000)
        return v, v
    return 0, 0


def parse_exp_bounds(text: str) -> tuple[int, int]:
    """解析经验要求区间（年）。(0,0) 表示未提供。"""
    s = text or ""
    m = EXP_RANGE_RE.search(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = EXP_PLUS_RE.search(s)
    if m:
        return int(m.group(1)), 99
    m = EXP_ONE_RE.search(s)
    if m:
        v = int(m.group(1))
        return max(0, v - 1), v + 2
    return 0, 0


def exp_wanted(exp_years: str) -> tuple[int, int]:
    """把筛选器经验档位转成区间；支持 "5-10" / "3-5" / "10+"（旧补丁 int("5-10") 会抛异常）。"""
    s = (exp_years or "any").strip()
    m = re.match(r"^(\d+)\s*[-~—]\s*(\d+)$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d+)\s*\+$", s)
    if m:
        return int(m.group(1)), 99
    return 0, 99


def volume_penalty(row: dict) -> tuple[int, list[str]]:
    """刷量降权：只看风险列与时间列（不扫 JD，避免"外包管理"这类误伤）。"""
    blob = " ".join(x for x in (
        _cell(row, "风险标记"), _cell(row, "依据"), _cell(row, "备注"), _cell(row, "发布时间"),
    ) if x)
    hits = [w for w in VOLUME_SIGNALS if w in blob]
    if not hits:
        return 0, []
    return -10, [f"刷量/虚假招聘信号：{'、'.join(hits[:3])}"]


def score_job(row: dict, ctx: JobQueryContext, status: str,
              company_batch: int = 0) -> dict[str, Any]:
    """岗位评分（0–100）：与「公司监控评分」完全分离，只看岗位本身与**本次筛选条件**的匹配。

    **薪资只读筛选器 `ctx.salary_min/salary_max`**，绝不读简历摘要，也不读其他来源。
    基础维度固定 7 项；命中刷量 / 同公司批量时才追加降权项。
    """
    parts: list[dict[str, Any]] = []
    reasons: list[str] = []
    field = lambda *n: _cell(row, *n)  # noqa: E731

    # ① 岗位真实性（30）
    t_ok, t_why = title_verdict(field("岗位", "职位"), ctx)
    if status == "verified" and t_ok:
        aut, aut_why = 30, "硬门槛全过"
    elif t_ok:
        aut, aut_why = 10, "岗位名合规，但有门槛未过"
    else:
        aut, aut_why = 0, t_why or "非具体岗位"
    score = aut
    parts.append({"维度": "岗位真实性", "得分": aut, "满分": 30, "依据": aut_why})
    if not t_ok and t_why:
        reasons.append(t_why)

    # ② 地区匹配（15）
    known, hit, r_why = region_verdict(field("地区", "工作地点"), ctx)
    if hit:
        reg = 15
    elif not known:
        reg = 5
        reasons.append(r_why or "地区缺失")
    else:
        reg = 0
        reasons.append(r_why)
    score += reg
    parts.append({"维度": "地区匹配", "得分": reg, "满分": 15,
                  "依据": r_why or field("地区", "工作地点")})

    # ③ 岗位匹配（15）
    title = field("岗位", "职位")
    hits = [k for k in ctx.keywords if k and (k in title or title in k)]
    if hits:
        kw = 15
    elif not ctx.keywords:
        kw = 10
    elif any(w in title for w in ("经理", "主管", "总监", "销售", "渠道", "区域", "城市", "大区", "省区")):
        kw = 8
    else:
        kw = 3
    score += kw
    parts.append({"维度": "岗位匹配", "得分": kw, "满分": 15,
                  "依据": "命中：" + "、".join(hits) if hits else title})

    # ④ 薪资匹配（15）—— 只看筛选器口径
    lo, hi = parse_salary(field("薪资"))
    want_lo = ctx.salary_min or 0
    want_hi = ctx.salary_max or 999999
    if not lo and not hi:
        sal, sal_why = 5, "薪资未公开"
    elif hi < want_lo:
        sal, sal_why = 0, f"{field('薪资')}（低于目标 {want_lo}-{want_hi}）"
    elif lo > want_hi:
        sal, sal_why = 8, f"{field('薪资')}（高于目标 {want_lo}-{want_hi}）"
    elif lo >= want_lo and hi <= want_hi:
        sal, sal_why = 15, f"{field('薪资')}（符合目标区间 {want_lo}-{want_hi}）"
    else:
        sal, sal_why = 12, f"{field('薪资')}（与目标区间部分重叠）"
    score += sal
    parts.append({"维度": "薪资匹配", "得分": sal, "满分": 15, "依据": sal_why})

    # ⑤ 经验匹配（10）
    elo, ehi = parse_exp_bounds(field("经验", "学历", "工作年限"))
    if ctx.exp_years in ("", "any"):
        exp = 8
    elif not elo:
        exp = 5
    else:
        wlo, whi = exp_wanted(ctx.exp_years)
        if ehi >= wlo and elo <= whi:
            exp = 10
        elif ehi >= max(0, wlo - 1):
            exp = 6
        else:
            exp = 2
    score += exp
    parts.append({"维度": "经验匹配", "得分": exp, "满分": 10,
                  "依据": f"{elo}-{ehi} 年 / 目标 {ctx.exp_years}" if elo else "经验要求未提供"})

    # ⑥ 行业匹配（10）
    # 锚定顺序很重要：**先看雇主（公司/行业/公司性质）**，JD 只作兜底。
    # 否则「食品公司」的 JD 里写一句"要求家电渠道经验"就会把行业判成目标行业（自检已覆盖该用例）。
    job_blob = " ".join([field("岗位", "职位"), field("JD")])
    comp_hit, comp_ok = industry_verdict(" ".join([field("公司"), field("行业"), field("公司性质")]))
    job_hit, job_ok = industry_verdict(job_blob)
    ctx_hits = [i for i in ctx.industries if i and i.lower() in (field("公司") + " " + job_blob).lower()]
    if comp_hit != "未知":
        if comp_ok:
            ind, ind_why = 10, comp_hit
        else:
            ind, ind_why = 2, f"行业不符：{comp_hit}"
            reasons.append(f"行业不符：{comp_hit}")
    elif ctx_hits or job_ok:
        ind, ind_why = 10, (job_hit if job_hit != "未知" else "、".join(ctx_hits))
    elif job_hit != "未知":
        ind, ind_why = 2, f"行业不符：{job_hit}"
        reasons.append(f"行业不符：{job_hit}")
    else:
        ind, ind_why = 5, "材料未体现行业"
    score += ind
    parts.append({"维度": "行业匹配", "得分": ind, "满分": 10, "依据": ind_why})

    # ⑦ 信息完整度（5）
    filled = sum(1 for v in (field("岗位", "职位"), field("公司"), field("地区", "工作地点"),
                             field("薪资"), field("经验", "学历", "工作年限"),
                             field("来源平台", "平台"), field("链接"))
                 if not is_placeholder(v))
    comp = max(0, min(5, round(filled / 7 * 5)))
    score += comp
    parts.append({"维度": "信息完整度", "得分": comp, "满分": 5, "依据": f"{filled}/7 字段齐全"})

    # ⑧ 刷量降权（只在命中时追加）
    pen, pen_reasons = volume_penalty(row)
    if pen:
        score += pen
        reasons += pen_reasons
        parts.append({"维度": "刷量降权", "得分": pen, "满分": 0, "依据": "；".join(pen_reasons)})

    # ⑨ 同公司批量降权（只在命中时追加）
    if company_batch >= 3:
        score -= 8
        reasons.append(f"同公司批量发布（本批 {company_batch} 条）")
        parts.append({"维度": "同公司批量降权", "得分": -8, "满分": 0,
                      "依据": f"该公司本批出现 {company_batch} 条"})

    total = max(0, min(100, score))
    layer = "优先投递" if total >= 80 else ("谨慎" if total >= 60 else "直接排除")
    return {"score": total, "layer": layer, "parts": parts, "reasons": reasons}


# ==========================================================
# 八、报告解析
# ==========================================================


def _parse_first_table(section: str) -> list[dict[str, str]]:
    """解析一段文本里的第一张 markdown 表（表头 → 单元格）。"""
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for ln in (section or "").splitlines():
        if not ln.strip().startswith("|"):
            if header:
                break
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if header is None:
            if len(cells) >= 3 and any(cells):
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) < len(header):
            continue
        rows.append({header[i]: cells[i] for i in range(len(header))})
        if len(rows) >= 200:
            break
    return rows


SECTION_PATTERNS: list[tuple[str, str]] = [
    ("pool", r"表\s*一|今日具体岗位|具体岗位池|具体岗位"),
    ("pending", r"待核实岗位|表\s*二(?![十])|待核实"),
    ("watch", r"目标公司监控|公司监控|表\s*三(?![十])"),
    ("intel", r"行业情报|行业新闻|表\s*四(?![十])"),
]


def split_sections(content: str) -> dict[str, str]:
    """按标题把报告切成 4 段：具体岗位 / 待核实 / 公司监控 / 行业情报。

    容错：找不到标题时退化为"整篇都当具体岗位段"（由硬门槛兜底过滤）。
    """
    lines = (content or "").splitlines()
    marks: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        head = re.sub(r"[#*\s]", "", ln)[:40]
        if not head:
            continue
        for key, pat in SECTION_PATTERNS:
            if re.search(pat, head):
                marks.append((i, key))
                break
    if not marks:
        return {"pool": content or "", "pending": "", "watch": "", "intel": ""}
    first: dict[str, int] = {}
    for i, key in marks:
        first.setdefault(key, i)
    order = sorted(first.items(), key=lambda kv: kv[1])
    out: dict[str, str] = {"pool": "", "pending": "", "watch": "", "intel": ""}
    for idx, (key, start) in enumerate(order):
        end = order[idx + 1][1] if idx + 1 < len(order) else len(lines)
        out[key] = "\n".join(lines[start:end])
    if order:
        out["pool"] = "\n".join(lines[: order[0][1]]) + "\n" + out["pool"]
    return out


def _annotate(row: dict, verdict: dict, ctx: JobQueryContext, company_batch: int = 0) -> dict:
    """写回判定与评分（对外契约：`_job_status` / `_score` / `_layer` / `_score_parts`）。"""
    row["_job_status"] = verdict["status"]
    row["_job_reasons"] = verdict["reasons"]
    row["_job_gates"] = {k: ("✅" if v else "❌") for k, v in verdict["gates"].items()}
    sc = score_job(row, ctx, verdict["status"], company_batch=company_batch)
    row["_score"] = str(sc["score"])
    row["_layer"] = sc["layer"]
    row["_score_parts"] = sc["parts"]
    row["_score_reasons"] = sc["reasons"]     # V2 新增：扣分原因（前端可展示）
    row["_score_kind"] = "岗位评分"            # 与公司监控评分（_company_score）区分
    row["真实性"] = verdict["status"]           # 兼容列名
    row["待核实原因"] = "；".join(verdict["reasons"])
    return row


def _route(row: dict, verdict: dict, from_pending: bool) -> str:
    """决定最终档位。

    - 表一：完全按判定结果（情报类 → invalid，直接出池）
    - 表二：模型已标"待核实" → 除非是情报/入口类标题，否则至少留在待核实（人工可看），
            满足全部硬门槛的升为 verified
    """
    if verdict["status"] == "verified":
        return "verified"
    if verdict["status"] == "invalid":
        if not from_pending:
            return "invalid"
        if is_intel_title(_cell(row, "岗位", "职位")):
            return "invalid"
        return "pending"
    return "pending"


def process_report(content: str, ctx: JobQueryContext, material: str = "") -> dict[str, Any]:
    """把模型报告切成四类，做真实性判定 + 岗位评分（**唯一判定路径**）。

    返回 {pool, pending, invalid, watch, intel, stats}
    """
    secs = split_sections(content)
    cand_rows = _parse_first_table(secs["pool"])
    pending_rows = _parse_first_table(secs["pending"])
    watch_rows = _parse_first_table(secs["watch"])
    intel_rows = _parse_first_table(secs["intel"])

    judged: list[tuple[dict, dict, bool]] = []
    for row in cand_rows:
        judged.append((row, classify(row, ctx, material), False))
    for row in pending_rows:
        judged.append((row, classify(row, ctx, material), True))

    # 同公司批量发布统计（用于降权）
    counts: dict[str, int] = {}
    for row, verdict, from_pending in judged:
        if _route(row, verdict, from_pending) in ("verified", "pending"):
            comp = _cell(row, "公司")
            if comp:
                counts[comp] = counts.get(comp, 0) + 1

    scored: dict[str, list[dict]] = {"verified": [], "pending": [], "invalid": []}
    for row, verdict, from_pending in judged:
        bucket = _route(row, verdict, from_pending)
        scored[bucket].append(_annotate(row, verdict, ctx, counts.get(_cell(row, "公司"), 0)))

    scored["verified"].sort(key=lambda x: int(x.get("_score") or 0), reverse=True)
    scored["pending"].sort(key=lambda x: int(x.get("_score") or 0), reverse=True)

    stats = {
        "candidates": len(cand_rows) + len(pending_rows),
        "verified": len(scored["verified"]),
        "pending": len(scored["pending"]),
        "invalid": len(scored["invalid"]),
        "watch": len(watch_rows),
        "intel": len(intel_rows),
    }
    return {"pool": scored["verified"], "pending": scored["pending"], "invalid": scored["invalid"],
            "watch": watch_rows, "intel": intel_rows, "stats": stats}


def verify_jobs(rows: list[dict], ctx: JobQueryContext,
                material: str = "") -> tuple[list[dict], list[dict]]:
    """兼容包装（旧补丁用过的函数名）：返回 (verified_rows, pending_rows)。

    真正的判定只有 `classify()` 一处，避免同一规则两套实现走偏；ai.py 走的是
    `process_report()`，本函数仅供外部脚本/旧调用方使用。
    """
    counts: dict[str, int] = {}
    verdicts = []
    for row in rows:
        v = classify(row, ctx, material)
        verdicts.append((row, v))
        if v["status"] in ("verified", "pending"):
            comp = _cell(row, "公司")
            if comp:
                counts[comp] = counts.get(comp, 0) + 1
    verified: list[dict] = []
    pending: list[dict] = []
    for row, v in verdicts:
        _annotate(row, v, ctx, counts.get(_cell(row, "公司"), 0))
        (verified if v["status"] == "verified" else pending).append(row)
    verified.sort(key=lambda x: int(x.get("_score") or 0), reverse=True)
    pending.sort(key=lambda x: int(x.get("_score") or 0), reverse=True)
    return verified, pending