"""公司风控体检引擎（公司背调升级版）。

设计分三层，**先确定性、后模型**：
  ① 规则层（本文件）：把公开工商/司法/舆情事实按阈值算成可复算的红旗结论与风险分——
     同样的输入永远得到同样的结论，可审计、可解释、不依赖模型状态；
  ② 检索层（ai.py 的 _gather_search）：按 18 个维度生成检索关键词，抓公开信息；
  ③ 模型层（ai.py 的 bgcheck）：只做定性补充、交叉印证与话术，不得推翻规则层的数值判定。

事实字段（FACTS_FIELDS）既是接口契约，也是前端表单的唯一来源（前端据此自动生成表单）。
所有字段可选：填得越多越准，缺失字段会在 missing 中列出并提示去哪里查。
"""
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------- 维度目录

RISK_DIMENSIONS: list[dict[str, Any]] = [
    {
        "id": "shell",
        "name": "空壳与实体真实性",
        "weight": "高",
        "key_questions": [
            "注册地址是否真实办公（集群注册 / 虚拟挂靠 / 一址多照）",
            "有无可访问官网、真实产品页面、真实客户案例",
            "人员是否实际到岗（参保人数与宣称规模是否匹配）",
            "是否只有招商/招聘页面，没有任何业务痕迹",
        ],
        "search_queries": [
            "{company} 注册地址 是否真实 办公",
            "{company} 官网 产品 客户案例",
            "{company} 空壳 骗局 投诉",
        ],
        "verify": "国家企业信用信息公示系统看注册地址与年报；实地或地图街景核对办公地；要一份盖章的业务合同样例",
    },
    {
        "id": "capital",
        "name": "资本真实性与实缴",
        "weight": "高",
        "key_questions": [
            "注册资本与实缴资本差距是否过大（认缴不等于实缴）",
            "成立多年是否长期零实缴 / 极低实缴",
            "是否出现减资、股东退出、出资方式为无形资产高评",
            "注册资本是否与其对外宣称的经营体量匹配",
        ],
        "search_queries": [
            "{company} 注册资本 实缴资本",
            "{company} 减资 股东变更",
        ],
        "verify": "公示系统年报「股东出资信息」；对比注册与实缴；关注认缴到期时间",
    },
    {
        "id": "ownership",
        "name": "股权、控制权与实际控制人",
        "weight": "中",
        "key_questions": [
            "股权是否多层嵌套、代持、频繁变更",
            "实际控制人是否为失信／被执行／有刑事记录",
            "法定代表人是否频繁更换（背锅法人风险）",
            "是否由无经营能力的个人或空壳公司控股",
        ],
        "search_queries": [
            "{company} 股东 实际控制人 股权穿透",
            "{company} 法定代表人 变更 失信",
        ],
        "verify": "公示系统股权穿透图；执行信息公开网查实控人；裁判文书网查实控人涉诉",
    },
    {
        "id": "identity",
        "name": "主体沿革与马甲史（换壳）",
        "weight": "高",
        "key_questions": [
            "是否频繁更名、频繁变更注册号／地址",
            "同一批人是否注册—运营—注销反复循环",
            "是否存在多个已注销的兄弟公司（做烂一个换一个）",
            "是否被吊销后立刻新设同类主体继续经营",
        ],
        "search_queries": [
            "{company} 曾用名 更名记录",
            "{company} 关联公司 注销",
            "{company} 同一法定代表人 公司 注销",
        ],
        "verify": "公示系统「历史信息」中的名称／地址变更记录；用法定代表人＋地址反查关联企业",
    },
    {
        "id": "address",
        "name": "经营场所与地址真实性",
        "weight": "中",
        "key_questions": [
            "注册地址是否为产业园／秘书公司集中注册地址",
            "招聘页面写的办公地址与注册地址是否一致",
            "是否无固定办公场所、纯远程／借用他人工位",
            "异地注册＋异地招聘（招人地无实体）",
        ],
        "search_queries": [
            "{company} 办公地址 招聘 地址",
            "{company} 产业园 集中注册",
        ],
        "verify": "地图／街景看楼宇；要求面试到实际办公地；看公示系统地址与招聘地址对照",
    },
    {
        "id": "staffing",
        "name": "参保人数与用人规模真实性",
        "weight": "高",
        "key_questions": [
            "社保参保人数是否为 0 或极少（人数量级不符）",
            "参保人数是否逐年下降（收缩信号）",
            "宣称百人团队但参保个位数",
            "招聘量大但用人规模极小（虚假招聘 / 储备简历）",
        ],
        "search_queries": [
            "{company} 参保人数 社保",
            "{company} 员工人数 规模",
        ],
        "verify": "公示系统年报「城镇职工基本养老保险信息」参保人数；面试时问团队在编人数与社保基数",
    },
    {
        "id": "litigation",
        "name": "涉诉总量与案由结构",
        "weight": "高",
        "key_questions": [
            "单位年限内的涉诉数量是否异常偏高",
            "案由集中在哪类（劳动争议／买卖／借贷／建设工程）",
            "是否被同一原告批量起诉（欠款、拖欠货款、欠薪）",
            "是否从被告变多、诉讼量逐年上升",
        ],
        "search_queries": [
            "{company} 裁判文书 案由",
            "{company} 开庭公告 被告",
        ],
        "verify": "中国裁判文书网＋人民法院公告网按公司名检索；注意同案由批量案件",
    },
    {
        "id": "enforcement",
        "name": "被执行、失信与限制高消费",
        "weight": "高",
        "key_questions": [
            "是否被列为被执行人、失信被执行人",
            "法定代表人／实控人是否被限制高消费",
            "是否有终本案件（无财产可供执行）",
            "执行标的金额是否远大于注册资本",
        ],
        "search_queries": [
            "{company} 被执行人 失信",
            "{company} 限制高消费",
        ],
        "verify": "中国执行信息公开网按名称／统一社会信用代码检索；核对案号与金额",
    },
    {
        "id": "contract",
        "name": "合同与买卖纠纷（上下游欠款）",
        "weight": "中",
        "key_questions": [
            "是否被供应商起诉索要货款（拖欠上游）",
            "是否与客户有大量质量／退款纠纷",
            "是否频繁作为被告出现在买卖合同中",
            "是否存在连环违约、履约能力不足",
        ],
        "search_queries": [
            "{company} 买卖合同纠纷 拖欠货款",
            "{company} 供应商 起诉",
        ],
        "verify": "裁判文书网按案由「买卖合同纠纷」筛选；问现有供应商账期是否正常",
    },
    {
        "id": "labor",
        "name": "劳动争议、欠薪与用工合规",
        "weight": "高",
        "key_questions": [
            "劳动争议案件数量与趋势（离职补偿／提成／加班费）",
            "是否上过欠薪黑名单／重大劳动保障违法行为名单",
            "是否长期不缴或按最低基数缴社保公积金",
            "是否存在克扣提成、押金、试用期不缴社保的集中投诉",
        ],
        "search_queries": [
            "{company} 劳动争议 劳动仲裁",
            "{company} 欠薪 拖欠工资",
            "{company} 员工 评价 克扣提成",
        ],
        "verify": "裁判文书网「劳动争议」案由；人社局欠薪名单／信用中国；脉脉、看准、黑猫投诉",
    },
    {
        "id": "regulatory",
        "name": "行政处罚与经营异常",
        "weight": "中",
        "key_questions": [
            "是否列入经营异常名录（未年报／失联）及是否已移出",
            "是否列入严重违法失信名单",
            "行政处罚次数与类型（市监／环保／安监／消防）",
            "是否有停产整顿、吊销许可记录",
        ],
        "search_queries": [
            "{company} 行政处罚",
            "{company} 经营异常 严重违法失信",
        ],
        "verify": "公示系统「行政处罚／经营异常」；信用中国；行业主管部门处罚公告",
    },
    {
        "id": "tax",
        "name": "税务与发票合规",
        "weight": "中",
        "key_questions": [
            "是否税务非正常户、有欠税公告",
            "是否长期零申报或走逃失联",
            "是否存在虚开发票、税收违法案件",
            "是否被列入重大税收违法失信主体",
        ],
        "search_queries": [
            "{company} 欠税公告 税务",
            "{company} 税收违法",
        ],
        "verify": "税务局欠税公告、重大税收违法失信主体信息公布栏；信用中国",
    },
    {
        "id": "finance",
        "name": "资金链与融资抵押",
        "weight": "中",
        "key_questions": [
            "是否有大量动产抵押、融资租赁（缺钱信号）",
            "股权是否被质押／冻结",
            "是否有对外担保、担保链风险",
            "应收账款／账期是否异常（用别人的钱周转）",
        ],
        "search_queries": [
            "{company} 股权质押 动产抵押",
            "{company} 对外担保",
        ],
        "verify": "公示系统「动产抵押／股权出质／股权冻结」；问账期与付款节奏",
    },
    {
        "id": "bankruptcy",
        "name": "破产、清算与注销风险",
        "weight": "高",
        "key_questions": [
            "是否进入破产重整／和解／清算程序",
            "是否已注销／吊销／停业／迁出",
            "是否有债权人申请破产的公告",
            "关联主体是否已批量注销",
        ],
        "search_queries": [
            "{company} 破产 重整 清算",
            "{company} 注销 吊销",
        ],
        "verify": "全国企业破产重整案件信息网；公示系统经营状态与清算组备案",
    },
    {
        "id": "public_opinion",
        "name": "舆情与雇主口碑",
        "weight": "中",
        "key_questions": [
            "近一年是否有重大负面新闻（欠薪、跑路、被查）",
            "员工评价是否集中在欠薪／克扣提成／强制加班",
            "投诉平台投诉量与投诉主题",
            "是否有消费者／加盟商集中维权",
        ],
        "search_queries": [
            "{company} 负面 新闻 欠薪 跑路",
            "{company} 投诉 维权",
            "{company} 员工评价 脉脉 看准",
        ],
        "verify": "黑猫投诉、脉脉、看准网、知乎、地方贴吧；按时间倒序看最近 12 个月",
    },
    {
        "id": "recruitment",
        "name": "招聘真实性与骗局红线",
        "weight": "高",
        "key_questions": [
            "是否存在招聘环节收费（押金／培训费／服装费／买产品）",
            "是否要求先交代理费、加盟费、保证金",
            "是否层级返利、拉人头特征（传销）",
            "是否外包／派遣／中介伪装成公司直招",
            "岗位是否长期挂出、多平台重复、面试不谈业务只谈缴费",
        ],
        "search_queries": [
            "{company} 招聘 押金 培训费 骗局",
            "{company} 面试 收费 投诉",
        ],
        "verify": "看到「先交钱」直接判定为红线；核对招聘主体与用人单位是否同一法人；问清劳动合同签署方",
    },
    {
        "id": "license",
        "name": "资质牌照与行业监管",
        "weight": "中",
        "key_questions": [
            "是否具备行业必需资质（金融／医疗／教育／危化／建筑／食品）",
            "资质是否即将到期或已被吊销",
            "是否有超范围经营（登记经营范围与主营不符）",
            "是否存在环保／安全／数据合规处罚",
        ],
        "search_queries": [
            "{company} 资质 许可证",
            "{company} 超范围经营",
        ],
        "verify": "行业主管部门官网许可查询；公示系统经营范围与许可信息对照",
    },
    {
        "id": "related",
        "name": "关联方与集团风险传导",
        "weight": "中",
        "key_questions": [
            "母／兄弟公司是否已有失信、被执行、破产记录",
            "同一实控人是否存在「做烂一家换一家」的模式",
            "是否互为担保、资金池、共用账户",
            "关联交易是否占收入主体（利润可被转移）",
        ],
        "search_queries": [
            "{company} 关联企业 集团",
            "{company} 母公司 兄弟公司 风险",
        ],
        "verify": "股权穿透看同一实控人下全部企业；逐个查执行与失信记录",
    },
]


# ------------------------------------------------------- 事实字段（表单契约）

# type: number 数字 / int 整数 / bool 是-否 / text 文本 / select 单选
FACTS_FIELDS: list[dict[str, Any]] = [
    # 主体与资本
    {"key": "reg_capital", "label": "注册资本（万元）", "type": "number", "group": "主体与资本", "essential": True, "help": "公示系统 / 企查查『注册资本』"},
    {"key": "paid_in_capital", "label": "实缴资本（万元）", "type": "number", "group": "主体与资本", "essential": True, "help": "年报『股东出资信息』；没有则填 0"},
    {"key": "established", "label": "成立时间（YYYY-MM）", "type": "text", "group": "主体与资本", "essential": True, "help": "如 2019-06；只填年份也可"},
    {"key": "status", "label": "经营状态", "type": "select", "group": "主体与资本", "essential": True,
     "options": ["存续", "在业", "吊销", "注销", "迁出", "停业", "清算", "其他"]},
    {"key": "insured_count", "label": "参保人数（人）", "type": "int", "group": "主体与资本", "essential": True, "help": "年报『城镇职工基本养老保险』人数；0 也要如实填"},
    {"key": "claimed_headcount", "label": "对外宣称员工规模（人）", "type": "int", "group": "主体与资本", "help": "招聘页面或官网宣称的人数"},
    {"key": "address_type", "label": "注册地址性质", "type": "select", "group": "主体与资本",
     "options": ["自有/写字楼", "集群注册", "虚拟挂靠", "不确定"]},
    {"key": "same_address_companies", "label": "同地址注册企业数", "type": "int", "group": "主体与资本", "help": "按注册地址检索，一址多照时数量"},
    {"key": "name_changes", "label": "曾用名次数", "type": "int", "group": "主体与资本"},
    {"key": "legal_rep_changes", "label": "法定代表人变更次数", "type": "int", "group": "主体与资本"},
    {"key": "related_companies", "label": "关联企业数", "type": "int", "group": "主体与资本"},
    {"key": "related_deregistered", "label": "已注销关联企业数", "type": "int", "group": "主体与资本", "help": "换壳/马甲史的重要指标"},
    {"key": "website", "label": "有可访问官网", "type": "bool", "group": "主体与资本"},
    {"key": "client_cases", "label": "有可查客户案例/中标", "type": "bool", "group": "主体与资本"},
    {"key": "tender_wins", "label": "公开中标记录数", "type": "int", "group": "主体与资本"},
    # 司法与执行
    {"key": "dishonest", "label": "失信被执行人", "type": "bool", "group": "司法与执行", "essential": True},
    {"key": "enforcement", "label": "被执行案件数", "type": "int", "group": "司法与执行", "essential": True},
    {"key": "enforcement_amount", "label": "执行标的合计（万元）", "type": "number", "group": "司法与执行"},
    {"key": "consumption_restriction", "label": "限制高消费", "type": "bool", "group": "司法与执行"},
    {"key": "judicial_total", "label": "司法案件总数", "type": "int", "group": "司法与执行", "essential": True},
    {"key": "labor_disputes", "label": "劳动争议案件数", "type": "int", "group": "司法与执行", "essential": True},
    {"key": "contract_disputes", "label": "合同/买卖纠纷数", "type": "int", "group": "司法与执行"},
    {"key": "loan_disputes", "label": "借贷纠纷数", "type": "int", "group": "司法与执行"},
    {"key": "court_announcements", "label": "开庭公告数", "type": "int", "group": "司法与执行"},
    {"key": "equity_frozen", "label": "股权冻结", "type": "bool", "group": "司法与执行"},
    {"key": "controlling_dishonest", "label": "实控人/法人失信", "type": "bool", "group": "司法与执行"},
    # 经营与监管
    {"key": "abnormal", "label": "经营异常名录", "type": "bool", "group": "经营与监管", "essential": True},
    {"key": "abnormal_moved_out", "label": "异常已移出", "type": "bool", "group": "经营与监管"},
    {"key": "serious_illegal", "label": "严重违法失信名单", "type": "bool", "group": "经营与监管"},
    {"key": "admin_penalties", "label": "行政处罚次数", "type": "int", "group": "经营与监管"},
    {"key": "tax_abnormal", "label": "税务非正常户", "type": "bool", "group": "经营与监管"},
    {"key": "tax_arrears", "label": "欠税公告", "type": "bool", "group": "经营与监管"},
    {"key": "bankruptcy", "label": "破产程序", "type": "select", "group": "经营与监管", "options": ["无", "重整", "和解", "清算"]},
    {"key": "chattel_mortgage", "label": "动产抵押数", "type": "int", "group": "经营与监管"},
    {"key": "equity_pledged", "label": "股权质押", "type": "bool", "group": "经营与监管"},
    {"key": "license_missing", "label": "缺行业必需资质", "type": "bool", "group": "经营与监管"},
    # 用工与舆情
    {"key": "wage_arrears_listed", "label": "欠薪黑名单/重大劳动保障违法", "type": "bool", "group": "用工与舆情", "essential": True},
    {"key": "social_arrears", "label": "社保欠缴/断缴投诉", "type": "bool", "group": "用工与舆情"},
    {"key": "severance_disputes", "label": "离职补偿/裁员争议数", "type": "int", "group": "用工与舆情"},
    {"key": "overtime_complaints", "label": "强制加班/超时用工投诉", "type": "bool", "group": "用工与舆情"},
    {"key": "work_injury_disputes", "label": "工伤纠纷数", "type": "int", "group": "用工与舆情"},
    {"key": "negative_news", "label": "近一年重大负面新闻", "type": "bool", "group": "用工与舆情"},
    {"key": "complaints", "label": "投诉平台投诉数", "type": "int", "group": "用工与舆情"},
    {"key": "complaint_topics", "label": "投诉集中问题", "type": "text", "group": "用工与舆情", "help": "如：克扣提成／不缴社保／押金不退"},
    {"key": "employer_rating", "label": "雇主评分（0-5）", "type": "number", "group": "用工与舆情"},
    {"key": "recruit_longterm", "label": "岗位长期挂出/多平台重复", "type": "bool", "group": "用工与舆情"},
    # 招聘与骗局红线
    {"key": "recruit_charging", "label": "招聘环节收费（押金/培训费/买产品）", "type": "bool", "group": "招聘与骗局红线", "essential": True},
    {"key": "franchise_fee", "label": "收代理费/加盟费/保证金", "type": "bool", "group": "招聘与骗局红线"},
    {"key": "pyramid", "label": "层级返利/拉人头特征", "type": "bool", "group": "招聘与骗局红线"},
    {"key": "outsourcing_agent", "label": "实为外包/派遣/中介伪装直招", "type": "bool", "group": "招聘与骗局红线"},
    {"key": "state_backed_claim", "label": "宣称国企/央企/政府背景", "type": "bool", "group": "招聘与骗局红线"},
    {"key": "interview_vague", "label": "面试不谈业务只谈缴费/材料", "type": "bool", "group": "招聘与骗局红线"},
]


class RiskFacts(BaseModel):
    """工商/司法/舆情公开事实（全部可选，填得越多结论越准）。"""

    company_name: str = ""
    reg_capital: Optional[float] = None
    paid_in_capital: Optional[float] = None
    established: Optional[str] = None
    status: Optional[str] = None
    insured_count: Optional[int] = None
    claimed_headcount: Optional[int] = None
    address_type: Optional[str] = None
    same_address_companies: Optional[int] = None
    name_changes: Optional[int] = None
    legal_rep_changes: Optional[int] = None
    related_companies: Optional[int] = None
    related_deregistered: Optional[int] = None
    website: Optional[bool] = None
    client_cases: Optional[bool] = None
    tender_wins: Optional[int] = None
    dishonest: Optional[bool] = None
    enforcement: Optional[int] = None
    enforcement_amount: Optional[float] = None
    consumption_restriction: Optional[bool] = None
    judicial_total: Optional[int] = None
    labor_disputes: Optional[int] = None
    contract_disputes: Optional[int] = None
    loan_disputes: Optional[int] = None
    court_announcements: Optional[int] = None
    equity_frozen: Optional[bool] = None
    controlling_dishonest: Optional[bool] = None
    abnormal: Optional[bool] = None
    abnormal_moved_out: Optional[bool] = None
    serious_illegal: Optional[bool] = None
    admin_penalties: Optional[int] = None
    tax_abnormal: Optional[bool] = None
    tax_arrears: Optional[bool] = None
    bankruptcy: Optional[str] = None
    chattel_mortgage: Optional[int] = None
    equity_pledged: Optional[bool] = None
    license_missing: Optional[bool] = None
    wage_arrears_listed: Optional[bool] = None
    social_arrears: Optional[bool] = None
    severance_disputes: Optional[int] = None
    overtime_complaints: Optional[bool] = None
    work_injury_disputes: Optional[int] = None
    negative_news: Optional[bool] = None
    complaints: Optional[int] = None
    complaint_topics: Optional[str] = None
    employer_rating: Optional[float] = None
    recruit_longterm: Optional[bool] = None
    recruit_charging: Optional[bool] = None
    franchise_fee: Optional[bool] = None
    pyramid: Optional[bool] = None
    outsourcing_agent: Optional[bool] = None
    state_backed_claim: Optional[bool] = None
    interview_vague: Optional[bool] = None


# ---------------------------------------------------------------- 规则引擎

SEVERITY_WEIGHT = {"veto": 40, "high": 18, "medium": 8, "low": 3, "info": 0}
SEVERITY_LABEL = {"veto": "一票否决", "high": "高风险", "medium": "中风险", "low": "提示", "info": "说明"}


def _f(finding_id: str, dimension: str, severity: str, title: str, detail: str,
       verify: str, advice: str = "") -> dict[str, Any]:
    return {
        "id": finding_id,
        "dimension": dimension,
        "severity": severity,
        "severity_label": SEVERITY_LABEL[severity],
        "title": title,
        "detail": detail,
        "verify": verify,
        "advice": advice,
    }


def _years_since(established: Optional[str]) -> Optional[float]:
    """把 'YYYY-MM' / 'YYYY/MM' / 'YYYY' 转成成立年数（近似，按月）。"""
    if not established:
        return None
    s = str(established).strip().replace("/", "-").replace(".", "-")
    parts = [p for p in s.split("-") if p.strip().isdigit()]
    if not parts:
        return None
    y = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 and 1 <= int(parts[1]) <= 12 else 6
    today = date.today()
    return round((today.year - y) + (today.month - m) / 12.0, 1)


def _fmt(x: Optional[float]) -> str:
    if x is None:
        return "未填"
    if isinstance(x, float) and x == int(x):
        return str(int(x))
    return str(x)


def evaluate(facts: "RiskFacts | dict[str, Any]") -> dict[str, Any]:
    """按规则算出风险红旗、风险分与等级。纯函数：同输入同输出。"""
    d: dict[str, Any] = facts.model_dump() if isinstance(facts, RiskFacts) else dict(facts)
    out: list[dict[str, Any]] = []

    org = d.get("company_name") or "该公司"
    years = _years_since(d.get("established"))
    reg = d.get("reg_capital")
    paid = d.get("paid_in_capital")
    insured = d.get("insured_count")
    claimed = d.get("claimed_headcount")

    # ---- 主体存续状态（一票否决类）----
    status = (d.get("status") or "").strip()
    if status in ("吊销", "注销", "清算", "停业", "迁出"):
        out.append(_f("status_dead", "破产、清算与注销风险", "veto",
                      f"经营状态为「{status}」",
                      "主体已无常经营能力，签约主体可能即将或已经消失。",
                      "公示系统核对状态与清算组备案；确认是否已换新主体承接业务。",
                      "不要入职或签约；若已谈妥，要求书面确认签约主体与社保缴纳主体。"))
    if (d.get("bankruptcy") or "无") not in ("无", "", None):
        out.append(_f("bankruptcy", "破产、清算与注销风险", "veto",
                      f"已进入破产程序：{d.get('bankruptcy')}",
                      "破产重整/和解/清算期间，欠薪与离职补偿受偿顺序受限。",
                      "全国企业破产重整案件信息网核对案号与公告。",
                      "优先确认工资与社保是否已拖欠，谨慎入职。"))
    if d.get("dishonest"):
        out.append(_f("dishonest", "被执行、失信与限制高消费", "veto",
                      "被列为失信被执行人",
                      "有履行能力而拒不履行生效判决，商业信用已实质性破产。",
                      "中国执行信息公开网核对案号、金额与失信情形。",
                      "一票否决：不建议入职、不建议签约合作。"))
    if d.get("serious_illegal"):
        out.append(_f("serious_illegal", "行政处罚与经营异常", "veto",
                      "列入严重违法失信名单",
                      "属市场监管最高级别失信认定，通常伴随持续违法经营。",
                      "公示系统「严重违法失信名单」核对列入原因与期限。",
                      "一票否决：先要求书面说明与整改证明。"))

    # ---- 骗局红线（一票否决类）----
    if d.get("recruit_charging"):
        out.append(_f("recruit_charging", "招聘真实性与骗局红线", "veto",
                      "招聘环节收费（押金/培训费/买产品）",
                      "《劳动合同法》第九条明确禁止用人单位向劳动者收取财物；此类招聘多为骗局。",
                      "保留收费凭证与聊天记录，向 12333、12315 举报。",
                      "一票否决：立即停止接触"))
    if d.get("franchise_fee"):
        out.append(_f("franchise_fee", "招聘真实性与骗局红线", "veto",
                      "以入职为条件收取代理费/加盟费/保证金",
                      "以「入职先交钱」为条件的招商型骗局特征。",
                      "确认收款主体与公司是否为同一法人；要求出具票据与合同条款。",
                      "一票否决：不缴任何费用"))
    if d.get("pyramid"):
        out.append(_f("pyramid", "招聘真实性与骗局红线", "veto",
                      "存在层级返利/拉人头特征",
                      "符合传销构成要件（入门费＋层级返利＋拉人头），涉刑风险。",
                      "对照《禁止传销条例》第七条；查是否有直销牌照。",
                      "一票否决：远离，涉及刑事风险。"))

    # ---- 资本真实性 ----
    if reg is not None and paid is not None and reg > 0:
        ratio = paid / reg
        if reg >= 1000 and ratio < 0.05:
            out.append(_f("capital_low_ratio", "资本真实性与实缴", "high",
                          f"实缴仅占注册资本 {ratio * 100:.1f}%（注册 {_fmt(reg)} 万 / 实缴 {_fmt(paid)} 万）",
                          "大额注册资本几乎未实缴，常见于撑门面或招投标门槛凑数，实际可动用资金有限。",
                          "公示系统年报「股东出资信息」核对实缴与认缴到期日。",
                          "入职前问清工资发放主体与现金流来源；合作前要求预付或缩短账期。"))
        elif paid == 0 and (years is None or years >= 3):
            out.append(_f("capital_zero_paid", "资本真实性与实缴", "high",
                          f"成立 {_fmt(years)} 年仍零实缴（注册 {_fmt(reg)} 万）",
                          "长期零实缴说明股东未真实投入，抗风险与赔付能力弱。",
                          "年报出资信息；核对是否有知识产权/实物高评出资。",
                          "把它当风险预算：一旦欠薪，可执行财产很可能不足。"))
    if reg is not None and reg < 100:
        out.append(_f("capital_small", "资本真实性与实缴", "medium",
                      f"注册资本仅 {_fmt(reg)} 万元",
                      "注册资本过小通常对应有限责任公司赔付能力有限（以认缴额为限承担责任）。",
                      "公示系统核对注册资本与责任形式。",
                      "关注工资拖欠后的可执行财产；谈薪时争取更短结算周期。"))
    amount = d.get("enforcement_amount")
    if amount is not None and reg and reg > 0 and float(amount) >= reg:
        out.append(_f("enforce_vs_capital", "被执行、失信与限制高消费", "high",
                      f"执行标的（{_fmt(float(amount))} 万）已达注册资本的 {float(amount) / reg * 100:.0f}%",
                      "被执行金额与注册资本同量级，说明对外债务已超出自身资本承受能力。",
                      "执行信息公开网核对案号与执行进展。",
                      "视为资金链紧张信号，谨慎入职与赊销合作。"))

    # ---- 空壳特征综合判断 ----
    shell_signals: list[str] = []
    if (d.get("address_type") or "") in ("集群注册", "虚拟挂靠"):
        shell_signals.append(f"注册地址为{d.get('address_type')}")
    if insured is not None and insured <= 3:
        shell_signals.append(f"参保仅 {insured} 人")
    if d.get("website") is False:
        shell_signals.append("无可访问官网")
    if d.get("client_cases") is False:
        shell_signals.append("无公开客户案例")
    if d.get("same_address_companies") and d["same_address_companies"] >= 5:
        shell_signals.append(f"同地址注册 {d['same_address_companies']} 家企业")
    if len(shell_signals) >= 3:
        out.append(_f("shell", "空壳与实体真实性", "high",
                      f"空壳特征叠加（{len(shell_signals)} 项）",
                      "命中：" + "；".join(shell_signals) + "。单看一项不致命，叠加出现时实体经营真实性存疑。",
                      "实地核对办公地；要求查看营业执照原件、业务合同样例、社保缴纳明细。",
                      "面试改到实际办公地；先做小额、短周期合作再谈长期。"))
    if d.get("same_address_companies") and d["same_address_companies"] >= 20:
        out.append(_f("cluster_address", "经营场所与地址真实性", "high",
                      f"同地址注册企业 {d['same_address_companies']} 家（集中注册地址）",
                      "典型秘书公司/产业园集中注册，多数为无实际办公的挂靠主体。",
                      "公示系统按地址反查企业清单；地图街景核对楼宇类型。",
                      "确认实际办公地在哪、是否有独立工位与门牌。"))

    # ---- 用人规模真实性 ----
    if insured is not None:
        if insured == 0:
            out.append(_f("insured_zero", "参保人数与用人规模真实性", "high",
                          "参保人数为 0",
                          "可能未开社保户、全员未缴或全部为劳务/灵活用工——直接影响五险一金与工龄连续性。",
                          "公示系统年报参保人数；面试时要求写明社保缴纳主体与基数。",
                          "把「入职即足额缴纳五险一金」写进书面确认，否则视为红线。"))
        if claimed and insured > 0 and insured < claimed * 0.2:
            out.append(_f("insured_mismatch", "参保人数与用人规模真实性", "high",
                          f"参保 {insured} 人 vs 宣称 {claimed} 人（不足 20%）",
                          "人数量级严重不符，常见于夸大团队规模或大量使用外包/兼职不缴社保。",
                          "要求提供部门在编人数与社保缴纳人数；核对招聘岗位与在编人数的匹配。",
                          "以参保人数作为真实规模基准，据此判断岗位是否有实际团队支撑。"))
        if insured <= 5 and d.get("recruit_longterm"):
            out.append(_f("recruit_vs_size", "招聘真实性与骗局红线", "high",
                          "长期大量招聘但参保人数极少",
                          "招聘规模与用人规模不符，可能是虚假招聘、储备简历或引流。",
                          "记录岗位挂出时长与重复平台数；核对面试后是否有真实录用流程。",
                          "先拿到明确岗位编制与汇报对象，再投入时间。"))
    if years is not None and years < 1:
        out.append(_f("young_company", "空壳与实体真实性", "medium",
                      f"成立仅 {years} 年（新设主体）",
                      "新设主体缺乏经营历史，无法用历史记录判断履约与发薪稳定性。",
                      "关注是否为老公司换壳新设；核对股东与法定代表人背景。",
                      "要求提供近 3 个月工资发放流水或社保缴纳截图。"))
    if years is not None and years < 2 and (reg is None or reg < 200) and (insured is None or insured <= 3):
        out.append(_f("young_tiny", "空壳与实体真实性", "high",
                      "新设 + 小资本 + 极少参保（三重叠加）",
                      "成立不足 2 年、注册资本偏小、参保极少，属典型新壳特征。",
                      "核对是否与已注销企业存在同一实控人/同一地址的承接关系。",
                      "不在未拿到书面 offer 与工资凭证前投入过多。"))

    # ---- 沿革与换壳 ----
    if (d.get("name_changes") or 0) >= 2:
        out.append(_f("name_changes", "主体沿革与马甲史（换壳）", "medium",
                      f"曾用名 {d['name_changes']} 次",
                      "频繁更名常用于摆脱历史负面记录或更换品牌外壳，需查清每次更名的原因。",
                      "公示系统「历史信息」核对更名时间与前后名称；按旧名再检索一次舆情与涉诉。",
                      "用曾用名重新检索裁判文书与投诉，很多负面只挂在旧名下。"))
    if (d.get("related_deregistered") or 0) >= 3:
        out.append(_f("shell_cycle", "主体沿革与马甲史（换壳）", "high",
                      f"已注销关联企业 {d['related_deregistered']} 家",
                      "同一实际控制人下多家企业连续注销，典型的「做烂一家换一家」经营模式。",
                      "按法定代表人＋股东穿透全部关联企业，逐个查执行与失信记录。",
                      "确认你的劳动合同签约主体是哪一家、是否为新设空壳。"))
    if (d.get("legal_rep_changes") or 0) >= 3:
        out.append(_f("legal_rep", "股权、控制权与实际控制人", "medium",
                      f"法定代表人变更 {d['legal_rep_changes']} 次",
                      "频繁更换法定代表人（或由无关人员挂名）是背锅法人/规避责任的常见特征。",
                      "核对现任法定代表人是否持股、是否为公司实际决策人。",
                      "签约时确认盖章主体与法人一致，保留沟通记录。"))

    # ---- 涉诉结构 ----
    jt = d.get("judicial_total") or 0
    if years and jt >= 5 and jt / max(years, 1) >= 2:
        out.append(_f("litigation_density", "涉诉总量与案由结构", "high",
                      f"司法案件 {jt} 件，约合每年 {jt / max(years, 1):.1f} 件",
                      "单位年限涉诉密度偏高，通常是履约/结算环节长期存在争议。",
                      "裁判文书网按年份看案件趋势与案由分布。",
                      "重点看是否集中在你要负责的业务环节（渠道费用、货款、提成）。"))
    if (d.get("labor_disputes") or 0) >= 5:
        out.append(_f("labor_many", "劳动争议、欠薪与用工合规", "high",
                      f"劳动争议案件 {d['labor_disputes']} 件",
                      "劳动争议集中说明薪酬/离职补偿环节纠纷常态化。",
                      "裁判文书网按「劳动争议」案由核对诉求类型（工资、提成、补偿金、社保）。",
                      "入职前把提成规则、结算周期、离职补偿写入书面。"))
    elif (d.get("labor_disputes") or 0) >= 2:
        out.append(_f("labor_some", "劳动争议、欠薪与用工合规", "medium",
                      f"劳动争议案件 {d['labor_disputes']} 件",
                      "已有可查的劳动争议记录，需确认争议主题是否与你的岗位相关。",
                      "核对案件年份与诉求；关注是否为同一批员工集体起诉。",
                      "留存工资条、考勤与提成计算规则。"))
    if (d.get("contract_disputes") or 0) >= 5:
        out.append(_f("contract_many", "合同与买卖纠纷（上下游欠款）", "high",
                      f"合同/买卖纠纷 {d['contract_disputes']} 件",
                      "大量买卖合同纠纷常见于拖欠供应商货款或质量违约，反映付款能力或商业信用问题。",
                      "核对公司是原告还是被告；被告居多说明是被追债方。",
                      "若你负责渠道/回款，先问清现有账期与坏账处理方式。"))
    if (d.get("loan_disputes") or 0) >= 3:
        out.append(_f("loan_many", "资金链与融资抵押", "high",
                      f"借贷纠纷 {d['loan_disputes']} 件",
                      "借贷类纠纷集中是资金链紧张的直接信号，往往先欠供应商再欠员工。",
                      "核对借贷金额与判决结果；结合被执行记录看偿付能力。",
                      "把工资结算周期与提成发放时点写进合同。"))
    if (d.get("court_announcements") or 0) >= 5:
        out.append(_f("announcements", "涉诉总量与案由结构", "low",
                      f"开庭公告 {d['court_announcements']} 条",
                      "开庭公告多说明诉讼在持续进行中，结果尚未落定，属于待观察风险。",
                      "人民法院公告网按日期跟踪后续判决与执行情况。",
                      "设立复盘时间点，一个月后重查。"))

    # ---- 执行与信用 ----
    if (d.get("enforcement") or 0) >= 3:
        out.append(_f("enforcement_many", "被执行、失信与限制高消费", "high",
                      f"被执行案件 {d['enforcement']} 件",
                      "多起被执行案件表明已进入强制执行阶段，资金与信用双重受压。",
                      "执行信息公开网核对每案标的、是否终本（无财产可执行）。",
                      "把「按时足额发薪」的保障条件谈成书面条款。"))
    elif (d.get("enforcement") or 0) >= 1:
        out.append(_f("enforcement_one", "被执行、失信与限制高消费", "medium",
                      f"被执行案件 {d['enforcement']} 件",
                      "存在被执行记录，需要看标的金额与是否已履行完毕。",
                      "执行信息公开网核对是否已履行、是否终本。",
                      "追问是否已结清；观察工资发放是否规律。"))
    if d.get("consumption_restriction"):
        out.append(_f("limit_high", "被执行、失信与限制高消费", "high",
                      "法定代表人/实控人被限制高消费",
                      "限高通常伴随未履行生效判决，说明主要责任人偿付能力或意愿存在问题。",
                      "执行信息公开网「限制消费令」核对被限制人与案号。",
                      "关注公司账户是否被冻结、报销与工资是否走私人账户。"))
    if d.get("controlling_dishonest"):
        out.append(_f("controller_dishonest", "股权、控制权与实际控制人", "high",
                      "实际控制人/法定代表人存在失信记录",
                      "关键人失信会直接传导到融资、投标与经营连续性。",
                      "按姓名检索执行信息公开网与裁判文书网。",
                      "确认关键人是否仍实际控制公司、有无变更计划。"))
    if d.get("equity_frozen"):
        out.append(_f("equity_frozen", "资金链与融资抵押", "high",
                      "存在股权冻结",
                      "股权被冻结通常源于债务纠纷，会限制融资与股权运作。",
                      "公示系统「股权冻结」核对执行法院与冻结期限。",
                      "视为资金紧张的强信号，谨慎投入长期资源。"))
    if d.get("equity_pledged"):
        out.append(_f("equity_pledged", "资金链与融资抵押", "medium",
                      "存在股权质押",
                      "股东以股权融资，若股价/估值下行可能引发平仓或控制权变动。",
                      "公示系统「股权出质」核对质权人与金额。",
                      "关注是否有控制权变更风险。"))
    if (d.get("chattel_mortgage") or 0) >= 3:
        out.append(_f("mortgage", "资金链与融资抵押", "medium",
                      f"动产抵押 {d['chattel_mortgage']} 条",
                      "频繁以设备/存货抵押融资，多出现在现金流偏紧、银行授信不足的阶段。",
                      "公示系统「动产抵押」核对抵押物与债权人。",
                      "问清回款与账期，争取短结算周期。"))

    # ---- 监管与税务 ----
    if d.get("abnormal") and not d.get("abnormal_moved_out"):
        out.append(_f("abnormal", "行政处罚与经营异常", "high",
                      "列入经营异常名录且未移出",
                      "常见原因为未按期年报或登记住所无法联系（失联），失联意味着主体可追溯性差。",
                      "公示系统核对列入原因、日期与是否已移出。",
                      "要求出示已移出证明；未移出前不签任何长期约定。"))
    elif d.get("abnormal") and d.get("abnormal_moved_out"):
        out.append(_f("abnormal_out", "行政处罚与经营异常", "low",
                      "曾列入经营异常名录（已移出）",
                      "历史异常已纠正，但仍需看原因与频率。",
                      "核对异常原因与移出时间，确认是否反复出现。",
                      "如为「住所无法联系」需实地确认办公地。"))
    if (d.get("admin_penalties") or 0) >= 3:
        out.append(_f("penalties", "行政处罚与经营异常", "medium",
                      f"行政处罚 {d['admin_penalties']} 次",
                      "多领域/多次处罚说明内控与合规管理薄弱。",
                      "信用中国按主体查询全部处罚决定书。",
                      "看处罚类型是否触及你的业务线（渠道、广告、用工）。"))
    if d.get("tax_abnormal") or d.get("tax_arrears"):
        out.append(_f("tax", "税务与发票合规", "high",
                      "税务非正常户" + ("、存在欠税公告" if d.get("tax_arrears") else ""),
                      "税务异常常与经营停滞或资金枯竭同步出现，也可能影响为你代扣代缴个税与社保。",
                      "税务局欠税公告、重大税收违法失信主体公布栏核对。",
                      "确认工资是否依法申报个税（看个税 APP 记录）。"))
    if d.get("license_missing"):
        out.append(_f("license", "资质牌照与行业监管", "high",
                      "缺少行业必需资质",
                      "无证经营随时可能被责令停业，直接影响岗位稳定与收入。",
                      "行业主管部门官网核对许可证编号与有效期。",
                      "要求提供许可证扫描件并在官方渠道验证。"))

    # ---- 用工与舆情 ----
    if d.get("wage_arrears_listed"):
        out.append(_f("wage_arrears", "劳动争议、欠薪与用工合规", "veto",
                      "列入欠薪黑名单/重大劳动保障违法行为",
                      "已被人社部门认定存在拖欠劳动报酬行为，属确定性欠薪事实。",
                      "人社局官网/信用中国核对公布记录与整改情况。",
                      "一票否决级风险：不建议入职，除非有可验证的清偿证据。"))
    if d.get("social_arrears"):
        out.append(_f("social_arrears", "劳动争议、欠薪与用工合规", "high",
                      "存在社保欠缴/断缴投诉",
                      "社保断缴直接影响医保、购房资格与工龄连续性。",
                      "当地社保/公积金 App 查询参保缴费明细（入职后第一时间核对）。",
                      "把「入职当月足额参保」写成书面条件并每月自查。"))
    if (d.get("severance_disputes") or 0) >= 3:
        out.append(_f("severance", "劳动争议、欠薪与用工合规", "medium",
                      f"离职补偿/裁员争议 {d['severance_disputes']} 件",
                      "离职环节纠纷集中，通常与主动裁员、补偿不足有关。",
                      "核对案件时间分布，判断是否处于集中裁员期。",
                      "问清人员流动率与近期组织调整。"))
    if d.get("overtime_complaints"):
        out.append(_f("overtime", "劳动争议、欠薪与用工合规", "low",
                      "存在强制加班/超时用工投诉",
                      "投诉集中反映工时管理问题，需当面确认作息与加班补偿。",
                      "对照招聘描述的作息；问清加班调休/加班费规则。",
                      "把作息与加班补偿写入 offer 沟通记录。"))
    if (d.get("work_injury_disputes") or 0) >= 2:
        out.append(_f("injury", "劳动争议、欠薪与用工合规", "medium",
                      f"工伤纠纷 {d['work_injury_disputes']} 件",
                      "工伤纠纷偏多说明现场安全管理与保险配置存在缺口。",
                      "核对是否足额缴纳工伤保险。",
                      "确认工伤险参保情况与安全培训制度。"))
    if d.get("negative_news"):
        out.append(_f("negative_news", "舆情与雇主口碑", "high",
                      "近一年存在重大负面新闻",
                      "负面新闻在时间上最近，对经营与雇主品牌的影响最直接。",
                      "按时间倒序核对新闻来源与后续处理结果（是否已解决）。",
                      "把负面事件的整改结果作为决策条件。"))
    if (d.get("complaints") or 0) >= 10:
        out.append(_f("complaints", "舆情与雇主口碑", "medium",
                      f"投诉平台投诉 {d['complaints']} 条",
                      "投诉量偏大，需看投诉主题是否与薪酬、提成、退款相关。",
                      "黑猫投诉等平台按时间排序读最近 20 条并统计主题。",
                      "把高频投诉主题在面试中逐条问清。"))
    if d.get("complaint_topics"):
        out.append(_f("complaint_topics", "舆情与雇主口碑", "info",
                      f"投诉集中问题：{d['complaint_topics']}",
                      "投诉主题是预判入职后痛点的最好线索。",
                      "在面试中直接就这些主题提问并要求书面答复。",
                      "把答复写入 offer 沟通记录，作为后续依据。"))
    if d.get("employer_rating") is not None and float(d.get("employer_rating") or 5) <= 2.5:
        out.append(_f("rating", "舆情与雇主口碑", "medium",
                      f"雇主评分偏低（{d['employer_rating']}/5）",
                      "员工评价是薪酬兑现与管理的先行指标之一。",
                      "看准/脉脉按时间读最近评价，注意是否有集中刷分。",
                      "把差评主题与面试答复对照。"))

    # ---- 招聘真实性 ----
    if d.get("outsourcing_agent"):
        out.append(_f("outsourcing", "招聘真实性与骗局红线", "high",
                      "实为外包/派遣/中介伪装直招",
                      "签约主体、社保主体与工作主体不一致，岗位稳定性与福利通常低于直招。",
                      "问清劳动合同签署方、社保缴纳方、汇报对象归属。",
                      "要求 offer 写明签约主体；不接受口头承诺。"))
    if d.get("state_backed_claim"):
        out.append(_f("state_claim", "股权、控制权与实际控制人", "high",
                      "宣称国企/央企/政府背景，需核验股权关系",
                      "冒用国资背景是招商、代理类骗局的高频手法。",
                      "公示系统穿透股权，确认是否存在国资股东；核对对方自称的集团名称。",
                      "让对方法务出具股权关系证明，或在官网核实隶属关系。"))
    if d.get("interview_vague"):
        out.append(_f("interview_vague", "招聘真实性与骗局红线", "high",
                      "面试不谈业务，只谈缴费/交材料",
                      "招聘流程异常，正常岗位面试核心是业务能力与岗位匹配。",
                      "坚持要求业务负责人面试并明确岗位职责与考核。",
                      "流程异常即停止推进。"))

    # ---- 汇总 ----
    veto_items = [x for x in out if x["severity"] == "veto"]
    score = min(100, sum(SEVERITY_WEIGHT[x["severity"]] for x in out))
    if veto_items:
        score = max(score, 75)
    if score <= 15:
        level, level_hint = "绿", "低风险：公开信息未见明显红旗，按常规核验即可"
    elif score <= 40:
        level, level_hint = "黄", "中风险：存在需核实的关注项，建议逐条问清并要求书面确认"
    elif score <= 70:
        level, level_hint = "橙", "高风险：多项红旗叠加，入职/签约前必须完成核实与兜底条款"
    else:
        level, level_hint = "红", "极高风险：已命中一票否决或多项高风险，强烈建议放弃"

    essential = [f for f in FACTS_FIELDS if f.get("essential")]
    missing = [f["label"] for f in essential if d.get(f["key"]) in (None, "")]
    provided = len(essential) - len(missing)
    confidence = round(provided / max(len(essential), 1), 2)

    order = {"veto": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    out.sort(key=lambda x: order[x["severity"]])

    return {
        "ok": True,
        "company": org,
        "score": score,
        "level": level,
        "level_hint": level_hint,
        "veto": bool(veto_items),
        "counts": {k: sum(1 for x in out if x["severity"] == k) for k in ("veto", "high", "medium", "low", "info")},
        "findings": out,
        "confidence": confidence,
        "missing": missing,
        "years": years,
    }


# ------------------------------------------------- 检索关键词与官方核查入口

OFFICIAL_PORTALS: list[dict[str, str]] = [
    {"name": "国家企业信用信息公示系统", "url": "https://www.gsxt.gov.cn/", "use": "注册资本/实缴/参保人数/经营异常/行政处罚/股权质押"},
    {"name": "中国裁判文书网", "url": "https://wenshu.court.gov.cn/", "use": "涉诉案由、劳动争议、买卖合同纠纷"},
    {"name": "中国执行信息公开网", "url": "http://zxgk.court.gov.cn/", "use": "被执行人、失信被执行人、限制高消费"},
    {"name": "信用中国", "url": "https://www.creditchina.gov.cn/", "use": "行政处罚、失信记录、欠薪与税务违法"},
    {"name": "全国企业破产重整案件信息网", "url": "https://pccz.court.gov.cn/", "use": "破产重整/清算公告"},
    {"name": "人民法院公告网", "url": "https://rmfygg.court.gov.cn/", "use": "开庭公告、送达公告、起诉状副本公告"},
    {"name": "国家税务总局·欠税与重大税收违法", "url": "https://www.chinatax.gov.cn/", "use": "欠税公告、重大税收违法失信主体"},
    {"name": "人社部门/信用中国·欠薪名单", "url": "https://www.creditchina.gov.cn/", "use": "重大劳动保障违法行为、欠薪黑名单"},
    {"name": "黑猫投诉", "url": "https://tousu.sina.com.cn/", "use": "消费者与员工投诉主题统计"},
    {"name": "看准网 / 脉脉", "url": "https://www.kanzhun.com/", "use": "员工评价、薪酬兑现口碑"},
]


@router.get("/risk/dimensions")
def risk_dimensions():
    """18 项风险维度目录 + 事实字段元数据（前端据此自动生成表单与说明）。"""
    groups: list[str] = []
    for f in FACTS_FIELDS:
        if f["group"] not in groups:
            groups.append(f["group"])
    return {
        "dimensions": RISK_DIMENSIONS,
        "fields": FACTS_FIELDS,
        "groups": groups,
        "portals": OFFICIAL_PORTALS,
        "severity_label": SEVERITY_LABEL,
    }


@router.post("/risk/evaluate")
def risk_evaluate(facts: RiskFacts):
    """规则层体检：同输入同输出，可审计、可复算，不依赖模型。"""
    return evaluate(facts)


@router.get("/risk/checklist")
def risk_checklist(company: str = "", top: int = 12):
    """生成核查清单：每个维度对应的检索关键词 + 官方查询入口（可复制自查）。"""
    name = (company or "").strip() or "公司名称"
    items: list[dict[str, Any]] = []
    used = 0
    for dim in RISK_DIMENSIONS:
        qs = [q.replace("{company}", name) for q in dim.get("search_queries") or []]
        if used >= max(1, min(30, top)):
            break
        items.append({
            "id": dim["id"],
            "name": dim["name"],
            "weight": dim["weight"],
            "key_questions": dim["key_questions"],
            "queries": qs,
            "verify": dim["verify"],
        })
        used += 1
    return {"ok": True, "company": name, "items": items, "portals": OFFICIAL_PORTALS}


def risk_queries(company: str, limit: int = 10) -> list[str]:
    """给背调检索用的深度风控关键词（优先高风险维度）。"""
    priority = ["enforcement", "labor", "public_opinion", "shell", "identity",
                "capital", "recruitment", "tax", "bankruptcy", "regulatory"]
    by_id = {d["id"]: d for d in RISK_DIMENSIONS}
    qs: list[str] = []
    for did in priority:
        dim = by_id.get(did)
        if not dim:
            continue
        for q in (dim.get("search_queries") or [])[:2]:
            qs.append(q.replace("{company}", company))
            if len(qs) >= limit:
                return qs
    return qs
