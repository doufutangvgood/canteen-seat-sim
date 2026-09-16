// 冒烟测试: 在最小 DOM/Canvas 桩上真实执行两个脚本块, 捕捉运行时错误。
const fs = require('fs'), path = require('path'), vm = require('vm');
const html = fs.readFileSync(path.join(__dirname, '食堂仿真沙盘.html'), 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);

let fails = 0;
const bad = m => { console.log('  BAD ' + m); fails++; };
const ok = m => console.log('  OK  ' + m);

// ---------- 最小 DOM ----------
const drawCalls = { fillRect: 0, fillText: 0, arc: 0, stroke: 0, roundRect: 0, lineTo: 0 };
function makeCtx() {
  const noop = () => {};
  const ctx = {
    setTransform: noop, clearRect: noop, beginPath: noop, closePath: noop,
    moveTo: noop, lineTo: () => drawCalls.lineTo++, stroke: () => drawCalls.stroke++,
    fill: noop, fillRect: () => drawCalls.fillRect++, arc: () => drawCalls.arc++,
    arcTo: noop, roundRect: () => drawCalls.roundRect++,
    fillText: () => drawCalls.fillText++,
    measureText: t => ({ width: String(t).length * 6 }),
    setLineDash: noop, save: noop, restore: noop, translate: noop, scale: noop,
  };
  return ctx;
}
class Ev { constructor(type) { this.type = type; } }
function makeEl(id) {
  const el = {
    id, value: '', checked: false, textContent: '', innerHTML: '', disabled: false,
    width: 0, height: 0, clientWidth: 900, clientHeight: 240,
    dataset: {}, children: [], style: {}, _ls: {},
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, on) { on === undefined ? (this._s.has(c) ? this._s.delete(c) : this._s.add(c))
                                      : (on ? this._s.add(c) : this._s.delete(c)); },
      contains(c) { return this._s.has(c); } },
    addEventListener(t, f) { (this._ls[t] = this._ls[t] || []).push(f); },
    dispatchEvent(e) { (this._ls[e.type] || []).forEach(f => f({ target: this, type: e.type })); return true; },
    closest() { return this; },
    getContext() { return (this._ctx = this._ctx || makeCtx()); },
    appendChild(c) { this.children.push(c); },
  };
  return el;
}
const els = {};
ids.forEach(i => els[i] = makeEl(i));
// 控件初值
const init = { p: '0.4', seats: '200', win: '8', clean: '0.4', load: '1.15',
               eat: '14', srv: '25', pat: '15', rep: '8' };
for (const k in init) els[k].value = init[k];
els.speed.value = '2';
// 分组按钮（真实 DOM 中它们是 <button>，具备 classList/dataset）
const mkBtn = data => { const e = makeEl('btn'); Object.assign(e.dataset, data); return e; };
els.pSeg.children = [mkBtn({ p: '0' }), mkBtn({ p: '0.4' }), mkBtn({ p: '1' })];
els.viewSeg.children = [mkBtn({ view: 'cur' }), mkBtn({ view: 'off' })];
const presets = ['quiet', 'base', 'busy', 'peak'].map(k => {
  const e = makeEl('preset_' + k); e.dataset = { preset: k }; return e;
});

let setTimeoutCalls = 0, intervalCalls = 0;
const sandbox = {
  console,
  document: {
    getElementById: id => els[id] || null,
    querySelectorAll: sel => sel === '[data-preset]' ? presets : [],
    addEventListener: () => {},
  },
  window: { devicePixelRatio: 2, addEventListener: () => {} },
  performance: { now: () => Date.now() },
  requestAnimationFrame: cb => cb(),
  setTimeout: (cb) => { setTimeoutCalls++; cb(); return 0; },   // 立即执行一次
  clearTimeout: () => {}, setInterval: () => { intervalCalls++; return 0; }, clearInterval: () => {},
  CanvasRenderingContext2D: function () {},
  Event: Ev, Math, Date, JSON, Object, Array, String, Number, isFinite, parseFloat, parseInt,
};
sandbox.CanvasRenderingContext2D.prototype = { roundRect: function () {} };
sandbox.globalThis = sandbox;
const ctx = vm.createContext(sandbox);

// ---------- 执行 ----------
console.log('=== 脚本执行 ===');
try {
  vm.runInContext(scripts[0], ctx, { filename: 'model.js' });
  ok('模型脚本加载成功');
} catch (e) { bad('模型脚本抛错: ' + e.stack.split('\n').slice(0, 3).join(' | ')); }

const t0 = Date.now();
try {
  vm.runInContext(scripts[1], ctx, { filename: 'ui.js' });
  ok(`UI 脚本首次渲染成功（含自动重算），用时 ${Date.now() - t0} ms`);
} catch (e) { bad('UI 脚本抛错: ' + e.stack.split('\n').slice(0, 4).join(' | ')); }

// ---------- 断言 ----------
console.log('\n=== 渲染产物断言 ===');
const kpiHtml = els.kpis.innerHTML;
const labels = ['有效座位使用率', '座位产出率', '占座空转', '平均找座等待',
                '平均打饭排队', '未落座流失率', '实际就餐人数', '高峰时段有效使用率'];
const miss = labels.filter(l => !kpiHtml.includes(l));
if (miss.length) bad('KPI 卡缺失: ' + miss.join(', ')); else ok(`8 张 KPI 卡全部渲染`);
if (kpiHtml.includes('NaN')) bad('KPI 中出现 NaN'); else ok('KPI 无 NaN');
if (kpiHtml.includes('（对比禁占座）')) ok('KPI 含"对比禁占座"增量'); else bad('KPI 缺少对照增量');

const status = els.status.textContent;
if (/完成/.test(status)) ok('状态栏: ' + status); else bad('状态栏异常: ' + status);

// 平面图: 座位 200 + 窗口 8 全部用 roundRect 绘制
const expectRR = 200 + 8;
if (drawCalls.roundRect >= expectRR)
  ok(`平面图绘制完整：roundRect ${drawCalls.roundRect} 次（座位 200 + 窗口 8）`);
else bad(`平面图座位绘制不足：roundRect ${drawCalls.roundRect} < ${expectRR}`);
if (drawCalls.fillText >= 30 && drawCalls.lineTo >= 300)
  ok(`图表绘制正常（文字 ${drawCalls.fillText} / 折线段 ${drawCalls.lineTo} / 等座圆点 ${drawCalls.arc}）`);
else bad(`图表绘制偏少: ${JSON.stringify(drawCalls)}`);
if (setTimeoutCalls >= 2 || intervalCalls >= 1) ok(`定时器已启动（setTimeout ${setTimeoutCalls} / setInterval ${intervalCalls}）`);

// 交互: 预设按钮 / 占座快捷按钮 / 视图切换 / 滑杆
console.log('\n=== 交互路径 ===');
try {
  presets[0].onclick();                            // 冷清日
  ok('预设按钮点击成功，load=' + els.load.value + ' p=' + els.p.value);
} catch (e) { bad('预设点击抛错: ' + e.message); }
try {
  els.pSeg._ls.click ? null : null;
  els.pSeg.onclick && els.pSeg.onclick({ target: els.pSeg.children[0] });
  els.pSeg.children[0].closest = () => els.pSeg.children[0];
  els.pSeg.onclick({ target: els.pSeg.children[0] });
  ok('占座快捷按钮点击成功，p=' + els.p.value);
} catch (e) { bad('占座按钮抛错: ' + e.message); }
try {
  els.viewSeg.children[1].closest = () => els.viewSeg.children[1];
  els.viewSeg.onclick({ target: els.viewSeg.children[1] });
  ok('平面图视图切换成功');
} catch (e) { bad('视图切换抛错: ' + e.message); }
try {
  els.seats.value = '260'; els.win.value = '11'; els.groups.checked = true; els.adaptive.checked = true;
  els.seats.dispatchEvent(new Ev('input')); els.win.dispatchEvent(new Ev('input'));
  els.groups.dispatchEvent(new Ev('change')); els.adaptive.dispatchEvent(new Ev('change'));
  ok('滑杆/复选框变更触发重算成功，座位=' + els.seats.value + ' 窗口=' + els.win.value);
} catch (e) { bad('控件变更抛错: ' + e.message); }
try {
  els.hmBtn.onclick.call(els.hmBtn);
  ok('热力图按钮执行成功');
} catch (e) { bad('热力图抛错: ' + e.message); }
try {
  els.play.onclick(); els.scrub.value = '60';
  els.scrub.oninput({ target: els.scrub }); els.speed.onchange();
  ok('播放/拖动/速度控件正常');
} catch (e) { bad('播放控件抛错: ' + e.message); }
try {
  els.scrub.value = '0';
  els.play.onclick();  // 恢复播放
  ok('动画帧渲染无异常');
} catch (e) { bad('动画抛错: ' + e.message); }

console.log(`\n${fails === 0 ? '冒烟测试全部通过 ✅' : fails + ' 项不通过 ❌'}`);
process.exit(fails ? 1 : 0);
