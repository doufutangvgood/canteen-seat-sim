// 从 HTML 中抽取仿真内核, 在 Node 中运行, 与 Python 模型结果对比。
const fs = require('fs');
const path = require('path');
const os = require('os');

const html = fs.readFileSync(path.join(__dirname, '食堂仿真沙盘.html'), 'utf8');
const m = html.match(/<script id="sim-model">([\s\S]*?)<\/script>/);
if (!m) { console.error('未找到 sim-model 脚本块'); process.exit(1); }
const tmp = path.join(os.tmpdir(), 'canteen_model_extract.js');
fs.writeFileSync(tmp, m[1], 'utf8');
const { runAvg, DEFAULTS } = require(tmp);

const SEEDS = Array.from({ length: 24 }, (_, i) => 1001 + i);   // 与 Python 相同的相对种子数
const BUSY = Object.assign({}, DEFAULTS, { load: 1.15 });

// Python(model.py, 24 reps, CRN) 的基准值
const PY = {
  '0':   { eff: 0.821, turn: 3.652, seatWait: 7.952, foodWait: 4.011, ab: 0.065, served: 1095.7, idlePre: 0.000 },
  '0.4': { eff: 0.760, turn: 3.309, seatWait: 9.260, foodWait: 0.938, ab: 0.153, served: 992.7,  idlePre: 0.039 },
  '1':   { eff: 0.762, turn: 3.311, seatWait: 9.403, foodWait: 0.034, ab: 0.152, served: 993.3,  idlePre: 0.050 },
};
const TOL = { eff: 0.020, turn: 0.10, seatWait: 0.80, foodWait: 0.60, ab: 0.030, served: 45, idlePre: 0.015 };

let fails = 0;
console.log('=== JS 引擎 vs Python 模型 (繁忙日, 各 24 次重复) ===');
const rows = {};
for (const p of [0, 0.4, 1]) {
  const t0 = Date.now();
  const { avg, ci } = runAvg(Object.assign({}, BUSY, { pSeatFirst: p }), SEEDS, false);
  const ms = (Date.now() - t0) / 24;
  rows[p] = avg;
  const ref = PY[String(p)];
  const chk = (name, js, py, tol) => {
    const d = Math.abs(js - py), ok = d <= tol;
    if (!ok) fails++;
    return `${ok ? 'OK ' : 'BAD'} ${name}=${js.toFixed(3)} (py ${py.toFixed(3)}, Δ${d.toFixed(3)})`;
  };
  console.log(`\n p=${p}  单次仿真 ${ms.toFixed(1)} ms`);
  console.log('  ' + chk('有效使用率', avg.seatEffectiveUtil, ref.eff, TOL.eff));
  console.log('  ' + chk('座位产出  ', avg.seatTurnoverPerHour, ref.turn, TOL.turn));
  console.log('  ' + chk('占座空转  ', avg.seatIdlePreUtil, ref.idlePre, TOL.idlePre));
  console.log('  ' + chk('找座等待  ', avg.seatWaitMean, ref.seatWait, TOL.seatWait));
  console.log('  ' + chk('打饭排队  ', avg.foodWaitMean, ref.foodWait, TOL.foodWait));
  console.log('  ' + chk('流失率    ', avg.abandonRatio, ref.ab, TOL.ab));
  console.log('  ' + chk('就餐人数  ', avg.peopleServed, ref.served, TOL.served));
  console.log(`     [参考] 名义占用率 ${avg.seatNominalUtil.toFixed(3)} | 高峰有效 ${avg.pkEffectiveUtil.toFixed(3)}` +
              ` | 长窗口有效 ${avg.seatEffectiveUtilW2.toFixed(3)} | 溢出比 ${avg.spillRatio.toFixed(3)}`);
}

// 结构一致性: 座位时间预算必须加总为 100%
console.log('\n=== 座位时间预算加总校验 ===');
for (const p of [0, 0.4, 1]) {
  const a = rows[p];
  const s = (a.seatEffectiveUtil + a.seatIdlePreUtil + a.seatIdleWalkUtil +
             a.seatCleanUtil + a.seatFreeUtil) * 100;
  const ok = Math.abs(s - 100) < 0.6;
  if (!ok) fails++;
  console.log(`  ${ok ? 'OK ' : 'BAD'} p=${p}: 合计 ${s.toFixed(2)}%`);
}

// 边界与稳定性
console.log('\n=== 边界与稳定性 ===');
const zero = runAvg(Object.assign({}, BUSY, { pSeatFirst: 0, nSeats: 400, load: 0.6 }), SEEDS, false).avg;
console.log(`  宽松情景: 就餐人数 ${zero.peopleServed.toFixed(0)}/${zero.peopleArrived.toFixed(0)}` +
            ` 流失 ${(zero.abandonRatio * 100).toFixed(1)}% 找座等待 ${zero.seatWaitMean.toFixed(2)} 分`);
const inf = runAvg(Object.assign({}, BUSY, { pSeatFirst: 0.4, maxSeatWait: 1e9 }), SEEDS, false).avg;
console.log(`  无限耐心: 就餐率 ${(inf.servedRate * 100).toFixed(1)}%` +
            ` 找座等待 ${inf.seatWaitMean.toFixed(2)} 分 (应≈13.5, Python 13.48)`);
if (Math.abs(inf.servedRate - 1) > 1e-9) { console.log('  BAD 无限耐心下应全部就餐'); fails++; }
if (Math.abs(inf.seatWaitMean - 13.48) > 1.2) { console.log('  BAD 无限耐心找座等待偏离'); fails++; }
const trace = runAvg(BUSY, SEEDS, true).avg.trace;
console.log(`  轨迹: ${trace.t.length} 帧 × ${trace.seats[0].length} 座位 = ` +
            `${(trace.t.length * trace.seats[0].length / 1024).toFixed(0)} KB`);
const bad = trace.seats.some(s => s.some(v => v < 0 || v > 3));
if (bad) { console.log('  BAD 轨迹中存在非法座位状态'); fails++; } else { console.log('  OK  座位状态取值合法'); }

console.log(`\n${fails === 0 ? '全部通过 ✅' : '存在 ' + fails + ' 项不通过 ❌'}`);
process.exit(fails === 0 ? 0 : 1);
