"""信号扫描（岗位雷达 / 背调共用的确定性词库层）。

回答四类"模型容易漏、但规则不会漏"的问题：
  ① 公司风险：检索材料里出现失信/被执行/欠薪/跑路/破产/投诉… → 直接标注风险关键词，不让岗位"看着香"就进推荐位
  ② 扩张利好：融资/上市/扩产/技术突破/中标 → 判断"是不是真的要扩人"
  ③ 刷量与虚假招聘：长期挂出、多平台重复、批量发布、猎头代招、收费陷阱 → 招聘真实性判定
  ④ 政策与产业：国家/地方规划、扶持目录、重点产业链 → 判断岗位所在赛道是否顺政策

为什么放在这里而不是提示词里：词库命中是**可复算的事实**，模型只负责解释命中含义。
扫描结果既注入提示词（强制落位到表格），也直接返回前端展示（模型漏了也能看见）。
"""
import re
from typing import Any, Iterable

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------- ① 公司风险词库

# (关键词, 维度, 严重度, 含义/为什么危险)
RISK_LEXICON: list[tuple[str, str, str, str]] = [
    # 执行与信用
    ("失信被执行人", "被执行与失信", "veto", "有履行能力而拒不履行生效判决，商业信用已实质性破产"),
    ("失信", "被执行与失信", "high", "失信记录，需核对主体与案号"),
    ("被执行人", "被执行与失信", "high", "已进入强制执行阶段，资金与信用双重受压"),
    ("限制高消费", "被执行与失信", "high", "关键人被限高，说明债务未履行"),
    ("终本", "被执行与失信", "high", "无财产可供执行，赔付能力已耗尽"),
    ("股权冻结", "股权与资金链", "high", "债务纠纷冻结股权，融资与股权运作受限"),
    ("破产重整", "破产与清算", "veto", "进入破产程序，欠薪与补偿受偿顺序受限"),
    ("破产", "破产与清算", "veto", "破产程序，主体与用工连续性存疑"),
    ("清算", "破产与清算", "high", "清算注销风险"),
    ("倒闭", "破产与清算", "veto", "已停止经营"),
    ("跑路", "破产与清算", "veto", "负责人失联、拖欠后逃逸的典型描述"),
    ("吊销", "主体状态", "high", "主体资格被吊销"),
    ("注销", "主体状态", "high", "主体已注销，签约与社保主体可能消失"),
    ("停业", "主体状态", "medium", "经营停滞"),
    ("经营异常", "经营与监管", "high", "多为未年报或住所失联；未移出则说明可追溯性差"),
    ("严重违法失信", "经营与监管", "veto", "市场监管最高级别失信认定"),
    ("行政处罚", "经营与监管", "medium", "存在被处罚记录"),
    ("欠税", "税务合规", "high", "欠税公告，通常与资金枯竭同步"),
    ("非正常户", "税务合规", "high", "税务非正常户，可能影响个税与社保代扣代缴"),
    ("虚开发票", "税务合规", "high", "涉税违法"),
    ("抽查不合格", "经营与监管", "low", "质量或合规抽检不合格"),
    # 用工与薪酬
    ("欠薪", "欠薪与劳动争议", "veto", "拖欠劳动报酬的确定性负面事实"),
    ("拖欠工资", "欠薪与劳动争议", "veto", "拖欠工资"),
    ("克扣提成", "欠薪与劳动争议", "high", "提成不兑现是渠道/销售岗最高频的坑"),
    ("不缴社保", "欠薪与劳动争议", "high", "未依法缴纳社保，影响医保与工龄连续性"),
    ("未缴社保", "欠薪与劳动争议", "high", "未缴社保"),
    ("断缴", "欠薪与劳动争议", "medium", "社保断缴影响购房/落户/医疗"),
    ("最低基数", "欠薪与劳动争议", "medium", "按最低基数缴社保，实际保障缩水"),
    ("劳动仲裁", "欠薪与劳动争议", "high", "进入仲裁程序"),
    ("劳动争议", "欠薪与劳动争议", "high", "劳动争议案件，多为工资/补偿/社保争议"),
    ("克扣", "欠薪与劳动争议", "medium", "克扣工资或提成"),
    ("裁员", "欠薪与劳动争议", "medium", "组织收缩或调整"),
    ("优化", "欠薪与劳动争议", "low", "行业黑话，常指裁员"),
    ("强制加班", "欠薪与劳动争议", "medium", "工时管理问题"),
    ("996", "欠薪与劳动争议", "low", "超时用工"),
    ("工伤", "欠薪与劳动争议", "medium", "工伤纠纷反映安全管理与保险缺口"),
    # 经营与资金
    ("资金链断裂", "资金链", "veto", "现金流出问题，往往先欠供应商再欠员工"),
    ("资金紧张", "资金链", "high", "现金流转紧"),
    ("债务违约", "资金链", "veto", "已发生违约"),
    ("逾期", "资金链", "medium", "付款或债务逾期"),
    ("欠款", "上下游欠款", "high", "被追讨货款或服务费"),
    ("拖欠货款", "上下游欠款", "high", "拖欠上游，反映付款能力或商业信用"),
    ("买卖合同纠纷", "上下游欠款", "medium", "常见于付款与质量争议"),
    ("借贷纠纷", "资金链", "high", "借贷类纠纷集中说明融资困难"),
    ("被执行标的", "被执行与失信", "high", "执行标的金额是偿付压力的直接量度"),
    ("动产抵押", "资金链", "medium", "以设备存货抵押融资，通常现金流偏紧"),
    ("股权质押", "资金链", "medium", "股东融资行为，存在控制权变动风险"),
    ("对外担保", "资金链", "medium", "担保链可能被关联方拖累"),
    ("查封", "被执行与失信", "high", "资产或账户被查封"),
    # 舆情与合规
    ("投诉", "舆情与口碑", "medium", "存在投诉记录，需看主题是否与薪酬相关"),
    ("维权", "舆情与口碑", "medium", "维权事件，常伴随集中投诉"),
    ("举报", "舆情与口碑", "medium", "被举报"),
    ("退费难", "舆情与口碑", "medium", "退款困难"),
    ("虚假宣传", "舆情与口碑", "low", "宣传与事实不符"),
    ("爆雷", "舆情与口碑", "veto", "集中违约或资金事件"),
    ("传销", "招聘骗局", "veto", "层级返利拉人头，涉刑风险"),
    ("培训贷", "招聘骗局", "veto", "以培训名义贷款，入职前负债"),
    ("押金", "招聘骗局", "veto", "招聘环节收取财物，法律明确禁止"),
    ("保证金", "招聘骗局", "high", "以入职为条件的保证金"),
    ("加盟费", "招聘骗局", "high", "招商型收费"),
    ("代理费", "招聘骗局", "high", "以代理资格收费"),
    ("买产品", "招聘骗局", "veto", "要求先买产品冲业绩"),
    ("套壳", "空壳与套壳", "high", "借壳/贴牌经营，主体与实际经营不一致"),
    ("空壳", "空壳与套壳", "high", "无实际经营实体"),
    ("皮包公司", "空壳与套壳", "high", "无实质资产与业务"),
    ("虚假招聘", "招聘真实性", "high", "招聘信息不真实"),
    ("挂靠", "空壳与套壳", "medium", "资质或地址挂靠"),
    ("冒用", "招聘真实性", "high", "冒用名义，需核验授权"),
]

# ---------------------------------------------------------------- ② 扩张利好词库

# (关键词, 类型, 强度 强/中, 对招聘的含义)
GROWTH_LEXICON: list[tuple[str, str, str, str]] = [
    ("完成融资", "融资", "强", "拿到钱通常意味着接下来扩编"),
    ("融资", "融资", "中", "资本动作，关注资金用途是否含团队扩张"),
    ("天使轮", "融资", "中", "早期轮次，团队从 0 到 1"),
    ("A轮", "融资", "强", "开始规模化，销售与渠道岗位需求上升"),
    ("B轮", "融资", "强", "扩张期，区域团队与渠道体系搭建"),
    ("C轮", "融资", "强", "上市前扩张，管理体系岗位增多"),
    ("战略投资", "融资", "强", "产业资本进入，常伴随业务协同与人员扩张"),
    ("pre-IPO", "融资", "强", "上市前冲刺，合规与财务岗位需求上升"),
    ("增资", "融资", "中", "注册资本或股权增资"),
    ("IPO", "上市", "强", "上市进程带来合规、财务、区域扩张需求"),
    ("上市", "上市", "强", "上市或有上市计划，信息透明度提升"),
    ("过会", "上市", "强", "上市审核通过"),
    ("递交招股书", "上市", "强", "进入上市流程"),
    ("并购", "资本运作", "中", "并购常伴随团队整合与渠道并入"),
    ("收购", "资本运作", "中", "收购方或标的方均可能扩编"),
    ("募投项目", "扩产", "强", "募资投向通常包含产能与渠道建设"),
    ("扩产", "扩产", "强", "产能扩张直接对应人员扩张"),
    ("新工厂", "扩产", "强", "新建产能"),
    ("投产", "扩产", "强", "新产能投产需要配套团队"),
    ("二期", "扩产", "中", "二期工程，规模翻倍信号"),
    ("开工", "扩产", "中", "项目开工"),
    ("奠基", "扩产", "中", "项目起步"),
    ("产能", "扩产", "中", "产能相关动作"),
    ("中标", "订单", "强", "拿到订单是招聘的直接前置信号"),
    ("签约", "订单", "中", "签约合作"),
    ("大单", "订单", "强", "大额订单"),
    ("战略合作", "订单", "中", "战略合作常带来新业务线"),
    ("技术突破", "技术", "强", "技术领先会带动产品与市场团队"),
    ("专利", "技术", "中", "技术储备"),
    ("首发", "产品", "中", "新品发布"),
    ("新品", "产品", "中", "新产品线需要新团队"),
    ("发布", "产品", "低", "发布动作"),
    ("出海", "市场", "强", "海外市场扩张，国际化岗位需求"),
    ("海外市场", "市场", "强", "海外布局"),
    ("渠道扩张", "市场", "强", "渠道扩张直接对应区域经理需求"),
    ("新增门店", "市场", "强", "门店扩张"),
    ("代理商招募", "市场", "强", "正在招代理，渠道体系扩张"),
    ("招商", "市场", "中", "招商加盟"),
    ("区域扩张", "市场", "强", "新区域进入"),
    ("政府补贴", "政策", "中", "获补贴说明政策支持"),
    ("专精特新", "政策", "中", "政策认定的成长型企业"),
    ("小巨人", "政策", "中", "专精特新小巨人"),
    ("高新技术企业", "政策", "中", "高企认定"),
    ("重点项目", "政策", "中", "列入重点项目"),
    ("独角兽", "资本运作", "中", "估值认可"),
]

# ---------------------------------------------------------------- ③ 刷量/虚假招聘词库

# (关键词, 信号, 强度)
VOLUME_LEXICON: list[tuple[str, str, str]] = [
    ("长期招聘", "长期挂出", "高"),
    ("常年招聘", "长期挂出", "高"),
    ("长期有效", "长期挂出", "高"),
    ("招满即止", "长期挂出", "中"),
    ("急招", "紧急补位或引流", "中"),
    ("大量招聘", "批量发布", "高"),
    ("大规模招聘", "批量发布", "高"),
    ("批量招聘", "批量发布", "高"),
    ("扩招", "批量发布", "中"),
    ("储备干部", "岗位虚化", "中"),
    ("储备人才", "岗位虚化", "高"),
    ("人才池", "岗位虚化", "中"),
    ("无需经验", "门槛异常", "中"),
    ("月入过万", "薪资异常", "中"),
    ("高薪急聘", "薪资异常", "中"),
    ("上不封顶", "薪资异常", "低"),
    ("包吃住", "福利异常", "低"),
    ("猎头代招", "非直招", "高"),
    ("代招", "非直招", "高"),
    ("外包", "非直招", "高"),
    ("劳务派遣", "非直招", "高"),
    ("人力资源服务", "非直招", "中"),
    ("中介", "非直招", "中"),
    ("兼职日结", "非直招", "中"),
    ("面试即入职", "流程异常", "高"),
    ("当天入职", "流程异常", "高"),
    ("收费", "疑似收费", "高"),
]

# ---------------------------------------------------------------- 通用扫描

# 公司名线索（用于统计"同一公司在检索里出现多少次"）
COMPANY_RE = re.compile(
    r"[\u4e00-\u9fff]{2,14}?(?:股份有限公司|有限责任公司|有限公司|集团|控股|科技|电器|电子|商贸|实业|食品|家居|新能源|机械|材料|软件|网络|供应链)"
)


def _snippet(text: str, kw: str, width: int = 46) -> str:
    i = text.find(kw)
    if i < 0:
        return ""
    lo = max(0, i - width)
    hi = min(len(text), i + len(kw) + width)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def scan(text: str, lexicon: Iterable[tuple], limit: int = 40) -> list[dict[str, Any]]:
    """在文本里扫描词库；返回命中项（含次数与上下文片段），按命中次数倒序。"""
    if not text:
        return []
    hits: list[dict[str, Any]] = []
    low = text.lower()
    for row in lexicon:
        kw = row[0]
        n = low.count(kw.lower())
        if n <= 0:
            continue
        extra = row[1:]
        item = {"keyword": kw, "count": n}
        if len(extra) == 3:
            item.update({"dimension": extra[0], "severity": extra[1], "meaning": extra[2]})
        elif len(extra) == 2:
            item.update({"type": extra[0], "strength": extra[1]})
        item["snippet"] = _snippet(text, kw)
        hits.append(item)
    hits.sort(key=lambda x: (-x["count"], x["keyword"]))
    return hits[:limit]


def scan_risk(text: str, limit: int = 40) -> list[dict[str, Any]]:
    return scan(text, RISK_LEXICON, limit)


def scan_growth(text: str, limit: int = 30) -> list[dict[str, Any]]:
    return scan(text, GROWTH_LEXICON, limit)


def scan_volume(text: str, limit: int = 30) -> list[dict[str, Any]]:
    return scan(text, VOLUME_LEXICON, limit)


def volume_rules(text: str) -> list[dict[str, Any]]:
    """刷量的**计数型**规则：同一公司在材料中反复出现、同标题重复、批量岗位数。

    只报"线索 + 计数值"，不下最终结论（最终结论由模型结合上下文给，或由界面提示人工核实）。
    """
    out: list[dict[str, Any]] = []
    if not text:
        return out
    # 1) 同一公司反复出现（标题/正文里出现次数）
    names: dict[str, int] = {}
    for m in COMPANY_RE.finditer(text):
        name = m.group(0)
        names[name] = names.get(name, 0) + 1
    for name, n in sorted(names.items(), key=lambda kv: -kv[1]):
        if n >= 5:
            out.append({"signal": "同一公司高频出现", "subject": name, "count": n,
                        "detail": f"检索材料中「{name}」出现 {n} 次，通常意味着多平台重复发布或批量挂岗"})
        if len(out) >= 6:
            break
    # 2) 同一标题重复出现（跨平台重复发布）
    titles: dict[str, int] = {}
    for m in re.finditer(r"\[(\d+)\.(\d+)\]\s*([^\n｜]{6,60})", text):
        t = re.sub(r"\s+", " ", m.group(3)).strip()
        titles[t] = titles.get(t, 0) + 1
    repeats = [(t, n) for t, n in titles.items() if n >= 2]
    for t, n in sorted(repeats, key=lambda kv: -kv[1])[:4]:
        out.append({"signal": "同标题多平台重复", "subject": t, "count": n,
                    "detail": f"标题「{t}」在检索中重复 {n} 次，疑似同一岗位多平台重复投放"})
    # 3) 招聘条目总量 vs 去重公司数（平均每公司岗位数）
    job_rows = len(re.findall(r"招聘|岗位|诚聘|急聘", text))
    company_cnt = len(names)
    if company_cnt and job_rows:
        avg = job_rows / max(company_cnt, 1)
        if avg >= 6:
            out.append({"signal": "批量发布", "subject": f"{company_cnt} 家公司 / {job_rows} 条招聘相关记录",
                        "count": int(avg),
                        "detail": f"平均每家公司出现约 {avg:.1f} 条招聘相关记录，疑似集中批量挂岗"})
    return out


def policy_queries(regions: list[str], industries: list[str]) -> list[str]:
    """国家 / 地方规划与扶持政策的检索路（政策层，非招聘层）。"""
    rg = regions[0] if regions else "河南"
    ind = industries[0] if industries else "家电"
    ind2 = industries[1] if len(industries) > 1 else ind
    qs = [
        f"{rg} 重点产业 规划 扶持 政策 {ind}",
        f"国家 {ind} 产业政策 十四五 规划 重点发展",
        f"{rg} {ind} 产业链 上下游 重点企业 名单",
    ]
    if ind2 != ind:
        qs.append(f"{ind2} 以旧换新 补贴 政策 落地")
    return qs


def growth_queries(companies: list[str], regions: list[str], industries: list[str]) -> list[str]:
    """扩张利好检索路：融资 / 上市 / 扩产 / 技术突破 / 中标。"""
    rg = regions[0] if regions else "河南"
    ind = industries[0] if industries else "家电"
    qs: list[str] = []
    if companies:
        qs.append(f"{companies[0]} 融资 上市 扩产 投资 最新")
    qs.append(f"{rg} {ind} 企业 融资 扩产 中标 技术突破 2025")
    return qs


def review_queries(companies: list[str], regions: list[str], industries: list[str]) -> list[str]:
    """雇主口碑检索路：优先可公开访问的来源（知乎/贴吧/投诉平台/新闻），
    看准与脉脉本身是登录墙平台，只能拿到检索摘要，不要指望抓正文。"""
    ind = industries[0] if industries else "家电"
    rg = regions[0] if regions else "河南"
    qs: list[str] = []
    if companies:
        qs.append(f"{companies[0]} 员工 待遇 评价 加班 提成 知乎")
    qs.append(f"{rg} {ind} 公司 拖欠 提成 投诉 黑猫 劳动仲裁 员工")
    return qs


# ---------------------------------------------------------------- 接口

class ScanRequest(BaseModel):
    text: str = ""


@router.get("/signals/lexicon")
def signals_lexicon():
    """词库说明（前端展示扫描了什么）。"""
    return {
        "ok": True,
        "risk": {
            "count": len(RISK_LEXICON),
            "items": [{"keyword": k, "dimension": d, "severity": s, "meaning": m} for k, d, s, m in RISK_LEXICON],
        },
        "growth": {
            "count": len(GROWTH_LEXICON),
            "items": [{"keyword": k, "type": t, "strength": st, "meaning": m} for k, t, st, m in GROWTH_LEXICON],
        },
        "volume": {
            "count": len(VOLUME_LEXICON),
            "items": [{"keyword": k, "signal": s, "strength": st} for k, s, st in VOLUME_LEXICON],
        },
    }


@router.post("/signals/scan")
def signals_scan(req: ScanRequest):
    """对任意文本做信号扫描（背调/助手/手工粘贴材料都可用）。"""
    text = req.text or ""
    risk = scan_risk(text)
    growth = scan_growth(text)
    volume = scan_volume(text)
    return {
        "ok": True,
        "risk": risk,
        "growth": growth,
        "volume": volume,
        "volume_rules": volume_rules(text),
        "summary": {
            "risk_hits": len(risk),
            "veto_hits": sum(1 for x in risk if x.get("severity") == "veto"),
            "growth_hits": len(growth),
            "volume_hits": len(volume),
            "chars": len(text),
        },
    }
