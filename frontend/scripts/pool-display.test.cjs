// 机会池展示逻辑单测（直接 require 由 tsc 编译出的真实实现）
//
// 跑法（在 frontend 目录下）：
//   node_modules\.bin\tsc src\lib\pool.ts --outDir tmp-pool --module commonjs --target es2020 --skipLibCheck --ignoreConfig
//   node scripts\pool-display.test.cjs
// 说明：tmp-pool 是编译产物（已在 .gitignore）；此脚本会自动补 commonjs 标记。
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, '..', 'tmp-pool');
if (!fs.existsSync(outDir)) {
  console.error('未找到编译产物 tmp-pool/，请先执行注释里的 tsc 命令。');
  process.exit(2);
}
fs.writeFileSync(path.join(outDir, 'package.json'), '{ "type": "commonjs" }\n');

const pool = require('../tmp-pool/pool.js');

let pass = 0, fail = 0;
const t = (name, fn) => {
  try { fn(); pass++; console.log('PASS ' + name); }
  catch (e) { fail++; console.log('FAIL ' + name + ' → ' + e.message); }
};

t('级解析：高中低 + ⚠️标记 + tone', () => {
  const a = pool.parseLevel('高');
  assert.strictEqual(a.level, '高'); assert.strictEqual(a.tone, 'high'); assert.strictEqual(a.rank, 3);
  const b = pool.parseLevel('低⚠️公司风险');
  assert.strictEqual(b.level, '低'); assert.strictEqual(b.tone, 'risk'); assert.deepStrictEqual(b.flags, ['公司风险']);
  const c = pool.parseLevel('中⚠️刷量（计数型线索，需核实）');
  assert.strictEqual(c.level, '中'); assert.strictEqual(c.tone, 'risk'); assert.deepStrictEqual(c.flags, ['刷量']);
  const d = pool.parseLevel('低（行业不符）');
  assert.strictEqual(d.level, '低'); assert.strictEqual(d.tone, 'low'); assert.strictEqual(d.note, '行业不符');
  const e = pool.parseLevel('待核实（无 JD）');
  assert.strictEqual(e.level, '待核实'); assert.strictEqual(e.rank, 0);
});

t('薪资解析：区间/单值/千元/万元月薪/年薪/无法解析', () => {
  assert.strictEqual(pool.salaryValue('10-15K·13薪'), 12500);
  assert.strictEqual(pool.salaryValue('20-40k'), 30000);
  assert.strictEqual(pool.salaryValue('15K'), 15000);
  assert.strictEqual(pool.salaryValue('1.5-2万'), 17500, '中文 JD 的「万」默认按月薪');
  assert.strictEqual(pool.salaryValue('年薪15-30万'), 18750, '写了「年薪」才按月折算');
  assert.strictEqual(pool.salaryValue('“高薪”未量化'), -1);
  assert.strictEqual(pool.salaryValue('材料未见'), -1);
});

t('总分解析与容错', () => {
  assert.strictEqual(pool.scoreValue({ _score: '81' }), 81);
  assert.strictEqual(pool.scoreValue({ _score: '79 分' }), 79);
  assert.strictEqual(pool.scoreValue({}), -1);
  assert.strictEqual(pool.scoreValue({ _score: '无法计算' }), -1);
});

t('列取值：模糊匹配列名 + 兜底', () => {
  const it = { '级': '高', '岗位': '区域经理', '公司': '博西家电', '经验/学历要求': '本科', 'JD 要点': '渠道下沉' };
  assert.strictEqual(pool.field(it, '经验', '学历'), '本科');
  assert.strictEqual(pool.field(it, 'JD'), '渠道下沉');
  assert.strictEqual(pool.field(it, '不存在的列'), '');
  assert.strictEqual(pool.cleanCompany({ '公司': 'Midea 美的 /' }), 'Midea 美的');
  assert.strictEqual(pool.cleanCompany({}), '公司未见');
});

t('去掉表一：保留表二及之后内容', () => {
  const md = [
    '**本批材料仅支撑 2 条**', '',
    '## 表一 · 机会池总表', '', '| 级 | 岗位 | 公司 |', '|---|---|---|', '| 高 | A | B |', '',
    '## 表二 · 加权评分总览', '', '| 公司/机会 | 加权总分 |', '|---|---|', '| B·A | 81 |',
  ].join('\n');
  const out = pool.stripPoolTables(md);
  assert.ok(!out.includes('| 高 | A | B |'), '表一表格行应被移除');
  assert.ok(out.includes('表二'), '表二应保留');
  assert.ok(out.includes('| B·A | 81 |'), '表二内容应保留');
});

t('去掉表一：兼容 **表一** 粗体写法', () => {
  const md = '**表一 · 机会池总表**\n| 级 | 岗位 |\n|---|---|\n| 高 | X |\n\n## 表二\n| a |\n|---|\n| 1 |';
  const out = pool.stripPoolTables(md);
  assert.ok(!out.includes('| 高 | X |'));
  assert.ok(out.includes('表二'));
});

t('CSV 导出：BOM + 表头 + 转义', () => {
  const csv = pool.toCsv([{ '级': '高', '岗位': '区域经理', '公司': 'A"B', '链接': '无' }]);
  assert.ok(csv.startsWith('\ufeff'));
  assert.ok(csv.includes('"岗位"'));
  assert.ok(csv.includes('"A""B"'), '引号应被转义');
});

t('真实数据回归：样例机会池全部可解析', () => {
  const p = path.join(__dirname, 'fixtures', 'pool-items.json');
  const items = JSON.parse(fs.readFileSync(p, 'utf8'));
  assert.ok(items.length >= 4);
  let withScore = 0, risky = 0;
  for (const it of items) {
    const lv = pool.parseLevel(pool.field(it, '级'));
    assert.ok(lv.level, '级必须解析出值');
    pool.salaryValue(pool.field(it, '薪资'));
    if (pool.scoreValue(it) >= 0) withScore++;
    if (lv.tone === 'risk') risky++;
  }
  assert.ok(withScore >= 2, '应能解析出加权总分');
  assert.ok(risky >= 2, '应识别出风险类条目');
  console.log(`   （样例：${items.length} 条，带总分 ${withScore}，风险标记 ${risky}）`);
});

console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
