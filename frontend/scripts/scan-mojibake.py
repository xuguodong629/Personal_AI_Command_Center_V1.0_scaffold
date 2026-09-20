"""修复「UTF-8 被按 CP936 解码」的乱码文件（可指定文件）。

⚠️ 安全设计（吃过一次亏）：只在**反向解码后常用字占比明显上升**时才替换，
   且只做**一趟**。上一版用「反向解码是否成功」当判据，会把本来正常的中文行二次反转 → 越修越坏。
   已经丢字节的**部分损坏**行无法自动还原，脚本会列出来，必须人工重写。

用法（项目根目录）：
    python frontend/scripts/scan-mojibake.py --dry-run 路径 [路径…]
    python frontend/scripts/scan-mojibake.py 路径 [路径…]
"""
import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = [ROOT / "frontend" / "src" / "styles.css"]

SIG = re.compile(r"[\u4e00-\u9fff]")
MOJI = set("锛銆涓鏂鐨勪簡鍦ㄦ槸鏈夌殑鍙璁惧搴鏇茬嚎鐢疆氱鑴鍖鐩鎴鍒浣缁鐞腑瀹瑙鍔鏁鎸鍜鎻绀鐗缂閿洏浼樺厛鎰悳绱鍏ュ彛懡浠ら潰鏉孯瀵瘑璋洪龆熷懆")
COMMON = set(
    "的一是不了在人有我他这中大来上国到说时要就出会可也你对生能而子那得于着下自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动面起看定天分还进好小部其些主样理心她本前开但因只从想实日军者意无它与长把机十民第公此已工使情明性知全三又关点正业外将两高间由问很最重并物手应战向头文体政美相见被利什二等产或新己制身果加西斯月话合回特代内信表化老给世位次度门任常先海通教儿原东声提立及比员解水名真论处走义各入几口认条平系气题活尔更别打女变四神总何电数安少报才结反受目太量再感建务做接必场件计管期市直德资命山金指克许统区保至队形社便空决治展马科司五基眼书非则听白却界达光放强即像难且权思王象完设式色路记南品住告类求据程北边死张该交规万取拉格望觉术领共确传师观清今切院让识候带导争运笑飞风步改收根干造言联持组每济车亲极林服快办议往元英士证近失转夫令准布始怎呢存未远叫台单影具罗字爱击流备兵连调深商算质团集百需价花党华城石级整府离况亚请技际约示复病息究线似官火断精满支视消越器容照须九增研写称企八功吗包片史委乎查轻易早曾除农找装广显吧阿李标谈吃图念六引历首医局突专费号尽另周较注语仅考落青随选列武红响虽推势参希古众构房半节土投某案黑维革划敌致陈律足态护七兴派孩验责营星够章音跟志底站严巴例防族供效续施留讲型料终答紧黄绝奇察母京段依批群项故按河米围江织害斗双境客纪采举杀攻父苏密低朝友诉止细愿千值仍男钱破网热助倒育属坐帝限船脸职速刻乐否刚威毛状率甚独球般普怕弹校苦创假久错承印晚兰试股拿脑预谁益阳若哪微尼继送急血惊伤素药适波夜省初喜卫源食险待述陆习置居劳财环排福纳欢雷警获模充负云停木游龙树疑层冷洲冲射略范竟句室异激汉村哈策演简卡罪判担州静退既衣您宗积余痛检差富灵协角占配征修皮挥胜降阶审沉坚善妈刘读啊超免压银买皇养伊怀执副乱抗犯追帮宣佛岁航优怪香著田铁控税左右份穿艺背阵草脚概恶块顿敢守酒岛托央户烈洋哥索胡款靠评版宝座释景顾弟登货互付伯慢欧换闻危忙核暗姐介坏讨丽良序升监临亮露永呼味野架域沙掉括舰鱼杂误湾吉减编楚肯测败屋跑均刷千"
)


def common_ratio(s: str) -> float:
    chs = SIG.findall(s)
    if len(chs) < 3:
        return 1.0
    return sum(1 for c in chs if c in COMMON) / len(chs)


def reverse(line: str) -> str | None:
    try:
        return line.encode("gbk", errors="strict").decode("utf-8", errors="strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    targets = [Path(a) for a in args] if args else DEFAULT
    total, manual = 0, 0
    for path in targets:
        if not path.is_absolute():
            cand = ROOT / path
            path = cand if cand.exists() else Path.cwd() / path
        if not path.exists():
            print(f"跳过（不存在）：{path}")
            continue
        lines = path.read_text("utf-8").splitlines(keepends=True)
        fixed_n = 0
        dirty: list[int] = []
        for i, ln in enumerate(lines, 1):
            if len(SIG.findall(ln)) < 3:
                continue
            before = common_ratio(ln)
            if before > 0.55:
                continue
            r = reverse(ln)
            if r and common_ratio(r) - before > 0.25:      # 只在这一明确条件下替换
                if dry:
                    print(f"  [{i}] {ln.strip()[:60]}\n    → {r.strip()[:60]}")
                lines[i - 1] = r if r.endswith("\n") else r + "\n"
                fixed_n += 1
            elif sum(1 for c in ln if c in MOJI) >= 3:
                dirty.append(i)
        if not dry and fixed_n:
            path.write_text("".join(lines), "utf-8")
        total += fixed_n
        manual += len(dirty)
        rel = path.relative_to(ROOT) if str(path).startswith(str(ROOT)) else path
        print(f"{rel}：{'待修复' if dry else '已修复'} {fixed_n} 行" + (f"；需人工重写 {len(dirty)} 行（{dirty[:8]}）" if dirty else ""))
    print(f"\n合计 {'待修复' if dry else '已修复'} {total} 行；需人工重写 {manual} 行")
    if manual:
        print("提示：无法自动还原的行请直接在编辑器里重写（不要再用 PowerShell 整体读写这些文件）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
