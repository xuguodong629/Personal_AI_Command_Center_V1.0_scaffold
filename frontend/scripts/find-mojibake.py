"""全仓排查「UTF-8 被按 CP936 解码」的乱码（只报告，不改文件）。

判据（比"能否反向编码"可靠）：
  把一行文本反向解码（encode gbk → decode utf-8）后，**常用字占比是否显著上升**。
  乱码行的汉字几乎全是生僻字（濮/涓/鏄…），正常中文行则大量命中常用字表。

用法（项目根目录）：python frontend/scripts/find-mojibake.py [目录…]
"""
import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"node_modules", ".venv", "dist", ".git", "target", "__pycache__", "tmp-pool", "cache", "models"}
EXTS = {".md", ".py", ".ts", ".tsx", ".css", ".json", ".bat", ".txt", ".yml", ".yaml"}

COMMON = set(
    "的一是不了在人有我他这中大来上国到说时要就出会可也你对生能而子那得于着下自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动面起看定天分还进好小部其些主样理心她本前开但因只从想实日军者意无它与长把机十民第公此已工使情明性知全三又关点正业外将两高间由问很最重并物手应战向头文体政美相见被利什二等产或新己制身果加西斯月话合回特代内信表化老给世位次度门任常先海通教儿原东声提立及比员解水名真论处走义各入几口认条平系气题活尔更别打女变四神总何电数安少报才结反受目太量再感建务做接必场件计管期市直德资命山金指克许统区保至队形社便空决治展马科司五基眼书非则听白却界达光放强即像难且权思王象完设式色路记南品住告类求据程北边死张该交规万取拉格望觉术领共确传师观清今切院让识候带导争运笑飞风步改收根干造言联持组每济车亲极林服快办议往元英士证近失转夫令准布始怎呢存未远叫台单影具罗字爱击流备兵连调深商算质团集百需价花党华城石级整府离况亚请技际约示复病息究线似官火断精满支视消越器容照须九增研写称企八功吗包片史委乎查轻易早曾除农找装广显吧阿李标谈吃图念六引历首医局突专费号尽另周较注语仅考落青随选列武红响虽推势参希古众构房半节土投某案黑维革划敌致陈律足态护七兴派孩验责营星够章音跟志底站严巴例防族供效续施留讲型料终答紧黄绝奇察母京段依批群项故按河米围江织害斗双境客纪采举杀攻父苏密低朝友诉止细愿千值仍男钱破网热助倒育属坐帝限船脸职速刻乐否刚威毛状率甚独球般普怕弹校苦创假久错承印晚兰试股拿脑预谁益阳若哪微尼继送急血惊伤素药适波夜省初喜卫源食险待述陆习置居劳财环排福纳欢雷警获模充负云停木游龙树疑层冷洲冲射略范竟句室异激汉村哈策演简卡罪判担州静退既衣您宗积余痛检差富灵协角占配征修皮挥胜降阶审沉坚善妈刘读啊超免压银买皇养伊怀执副乱抗犯追帮宣佛岁航优怪香著田铁控税左右份穿艺背阵草脚概恶块顿敢守酒岛托央户烈洋哥索胡款靠评版宝座释景顾弟登货互付伯慢欧换闻危忙核暗姐介坏讨丽良序升监临亮露永呼味野架域沙掉括舰鱼杂误湾吉减编楚肯测败屋跑均刷千"
)
SIG = re.compile(r"[\u4e00-\u9fff]")
# 乱码高频字：CP936 解 UTF-8 字节后的典型产物（用于识别**部分损坏**：反向解码已不可逆的情况）
MOJI = set("锛銆涓鏂鐨勪簡鍦ㄦ槸鏈夌殑鍙璁惧搴鏇茬嚎鐢疆氱鑴鍖鐩鎴鍒浣缁鐞腑瀹瑙鍔鏁鎸鍜鎻绀鐗缂閿洏浼樺厛鎰悳绱鍏ュ彛懡浠ら潰鏉孯瀵瘑璋洪龆熷懆鎷涜仒缃戠珯寮忕瓫閫夐潰鏉鎻愮ず杩涚▼绌虹姸鎬佸鍒撶粨鏋滃尯鍩虹鎬佺潃")


def cjk_ratio_common(s: str) -> float:
    chs = SIG.findall(s)
    if len(chs) < 3:
        return 1.0
    return sum(1 for c in chs if c in COMMON) / len(chs)


def reverse(line: str) -> str | None:
    try:
        return line.encode("gbk", errors="strict").decode("utf-8", errors="strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None


def moji_count(line: str) -> int:
    return sum(1 for c in line if c in MOJI)


def main() -> int:
    roots = [Path(a) for a in sys.argv[1:]] or [ROOT]
    hits: list[tuple[Path, int, str, float, float]] = []
    scanned = 0
    for root in roots:
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in EXTS:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            try:
                text = p.read_text("utf-8")
            except Exception:
                continue
            scanned += 1
            for i, ln in enumerate(text.splitlines(), 1):
                if len(SIG.findall(ln)) < 3:
                    continue
                before = cjk_ratio_common(ln)
                if before > 0.55:
                    continue                      # 本来就是正常中文
                # ① 可逆乱码：反向解码后常用字占比明显上升
                r = reverse(ln)
                if r and cjk_ratio_common(r) - before > 0.25:
                    hits.append((p, i, ln.strip()[:80], before, cjk_ratio_common(r)))
                    continue
                # ② 部分损坏（字节丢失，反向解码失败）：乱码高频字密集出现
                if moji_count(ln) >= 3:
                    hits.append((p, i, ln.strip()[:80] + "  ← 不可逆，需人工重写", before, -1.0))
    print(f"扫描 {scanned} 个文本文件，发现疑似乱码 {len(hits)} 行")
    by_file: dict[Path, int] = {}
    for p, _i, _t, _b, _a in hits:
        by_file[p] = by_file.get(p, 0) + 1
    for p, n in sorted(by_file.items(), key=lambda kv: -kv[1]):
        rel = p.relative_to(ROOT) if str(p).startswith(str(ROOT)) else p
        print(f"  {rel}：{n} 行")
        for pp, i, t, b, a in hits:
            if pp == p:
                print(f"      [{i}] 常用字 {b:.0%} → 修正后 {a:.0%} ｜ {t[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
