// 静态检查: 脚本语法 + DOM id 引用完整性 + 关键调用一致性 + 站点入口
// 用法: node check_html.js [要检查的 html 路径]   (默认 index.html；可指向线上抓取的副本)
const fs = require('fs'), path = require('path'), vm = require('vm');
const target = process.argv[2] ? path.resolve(process.argv[2]) : path.join(__dirname, 'index.html');
const html = fs.readFileSync(target, 'utf8');
console.log('检查文件: ' + target);

let fails = 0;
const bad = m => { console.log('  BAD ' + m); fails++; };
const ok = m => console.log('  OK  ' + m);

// 1) 所有内联脚本的语法
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]);
console.log('=== 脚本语法 ===');
scripts.forEach((s, i) => {
  try { new vm.Script(s, { filename: `inline-${i}.js` }); ok(`脚本块 ${i} 语法正确 (${s.split('\n').length} 行)`); }
  catch (e) { bad(`脚本块 ${i} 语法错误: ${e.message}`); }
});

// 2) id 引用完整性
console.log('\n=== DOM id 引用 ===');
const defined = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
const used = new Set();
for (const m of html.matchAll(/\$\('([^']+)'\)/g)) used.add(m[1]);
for (const m of html.matchAll(/getElementById\('([^']+)'\)/g)) used.add(m[1]);
for (const m of html.matchAll(/\$\('o_' \+ id\)/g)) { /* 动态生成 */ }
['p', 'seats', 'win', 'clean', 'load', 'eat', 'srv', 'pat', 'rep'].forEach(id => used.add('o_' + id));
const missing = [...used].filter(id => !defined.has(id));
if (missing.length) bad('引用了不存在的 id: ' + missing.join(', '));
else ok(`引用的 ${used.size} 个 id 全部存在`);
const unused = [...defined].filter(id => !used.has(id) && !html.includes(`data-${id}`));
if (unused.length) console.log('  （未被 $() 引用的 id: ' + unused.join(', ') + '）');

// 3) data-* 契约
console.log('\n=== 事件/数据契约 ===');
const dp = [...html.matchAll(/data-p="([^"]+)"/g)].map(m => m[1]);
if (dp.length === 3) ok('占座快捷按钮 data-p = ' + dp.join(' / ')); else bad('data-p 数量异常: ' + dp.length);
const dpr = [...html.matchAll(/data-preset="([^"]+)"/g)].map(m => m[1]);
const presetKeys = (html.match(/quiet:\s*\{[\s\S]*?\}\s*\}/) || [''])[0];
const missingPreset = dpr.filter(k => !new RegExp(k + ':\\s*\\{').test(html));
if (missingPreset.length) bad('预设按钮无对应配置: ' + missingPreset.join(', '));
else ok('4 个预设按钮均有配置: ' + dpr.join(' / '));
const dv = [...html.matchAll(/data-view="([^"]+)"/g)].map(m => m[1]);
if (dv.join() === 'cur,off') ok('视图切换 data-view = cur / off'); else bad('data-view 异常: ' + dv.join());

// 4) 模型接口一致性: UI 用到的指标名必须由 collect() 产出
console.log('\n=== 指标字段 ===');
const model = scripts.find(s => s.includes('seatEffectiveUtil'));
const ui = scripts.find(s => s.includes('renderKpis'));
// 精确定位 collect() 方法体, 取其最后一个 return { ... } 的键名
function collectKeys(src) {
  const s = src.indexOf('collect() {');
  if (s < 0) return new Set();
  const b0 = src.indexOf('{', s);
  let depth = 0, end = b0;
  for (let i = b0; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { end = i; break; } }
  }
  const body = src.slice(b0, end);
  const ri = body.lastIndexOf('return {');
  return new Set([...body.slice(ri).matchAll(/(?:^|[{,\s])([a-zA-Z_$][\w$]*)\s*:/g)].map(m => m[1]));
}
const produced = collectKeys(model);
const JS_BUILTIN = new Set(['toFixed', 'length', 'slice', 'dataset', 'onclick', 'style', 'value',
  'textContent', 'name', 'message', 'x', 'y', 'w', 'axis', 'color', 'band', 'dots', 'dash',
  'series', 'series2', 'xLabel', 'vline', 'vlineLabel', 'fmtX', 'fmtZ', 'dy', 'cats', 'values',
  'rows', 'cols', 'fmt', 't', 'r', 'b', 'avg', 'ci', 'push', 'map', 'filter', 'target', 'closest']);
const needed = new Set();
for (const re of [/\b(?:r|b|avg|a|d)\.([a-zA-Z][a-zA-Z0-9]*)/g]) {
  for (const m of ui.matchAll(re)) needed.add(m[1]);
}
const lack = [...needed].filter(k => !JS_BUILTIN.has(k) && !produced.has(k));
if (!produced.size) bad('未能解析 collect() 返回字段');
else if (lack.length) bad('UI 引用了模型未产出的字段: ' + lack.join(', '));
else ok(`collect() 产出 ${produced.size} 个字段; UI 引用的 ${[...needed].filter(k => !JS_BUILTIN.has(k)).length} 个指标全部匹配`);

// 5) 关键单位/口径
console.log('\n=== 口径 ===');
if (/exponential\(lamMax\)/.test(model)) ok('到达过程使用 lamMax 作为速率（均值 1/lamMax）');
else bad('到达过程速率传参可能错误');
if (/all\b[\s\S]{0,400}?T\.k|for \(const k of Object\.keys\(rows\[0\]\.ts\)\)/.test(model))
  ok('时间序列跨重复取均值');
else bad('时间序列未取均值');
// 6) 站点入口（GitHub Pages）
console.log('\n=== 站点入口 ===');
const stub = fs.readFileSync(path.join(__dirname, '食堂仿真沙盘.html'), 'utf8');
if (/url=\.\/index\.html/.test(stub) && /location\.replace\('\.\/index\.html'\)/.test(stub))
  ok('中文名入口页正确跳转到 index.html');
else bad('中文名入口页未正确跳转');
if (fs.existsSync(path.join(__dirname, '.nojekyll'))) ok('.nojekyll 存在（跳过 Jekyll 处理）');
else bad('缺少 .nojekyll');
console.log(`\n${fails === 0 ? '静态检查全部通过 ✅' : fails + ' 项不通过 ❌'}`);
process.exit(fails ? 1 : 0);
