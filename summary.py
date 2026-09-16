# -*- coding: utf-8 -*-
"""汇总所有实验结果, 输出供撰写报告用的数字清单。"""
import pandas as pd, numpy as np
pd.set_option("display.width", 250, "display.max_columns", 60)

def show(t):
    print("\n" + "=" * 104); print(t); print("=" * 104)

show("E1 占座比例扫描 (关键指标)")
for tag in ("base", "busy"):
    d = pd.read_csv(f"results/e1_p_sweep_{tag}.csv")
    c1 = ["p", "seat_effective_util", "pk_effective_util", "seat_nominal_util",
          "seat_idle_pre_util", "seat_turnover_per_hour", "seat_wait_mean",
          "food_wait_mean", "abandon_ratio", "people_served"]
    c2 = ["p", "total_time_mean", "wait_person_min_per_head", "pre_claimed_share",
          "instant_claim_share", "seat_effective_util_w2", "spill_ratio", "seat_free_util"]
    for c in (c1, c2):
        print(f"\n--- {tag} ---")
        print(d[c].round(3).to_string(index=False))
    for p in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        r = d[d.p.round(2) == p].iloc[0]
        print(f"  p={p:.1f}: 有效{r.seat_effective_util*100:5.1f}% 高峰{r.pk_effective_util*100:5.1f}% "
              f"名义{r.seat_nominal_util*100:5.1f}% 空转{r.seat_idle_pre_util*100:4.1f}pp "
              f"产出{r.seat_turnover_per_hour:.2f} 找座{r.seat_wait_mean:5.2f} 打饭{r.food_wait_mean:5.2f} "
              f"流失{r.abandon_ratio*100:4.1f}% 服务{r.people_served:6.0f}")

show("E2 相图: 不同客流强度下 p 从 0->1 的变化")
d = pd.read_csv("results/e2_load_p.csv")
for ld, g in d.groupby("load_scale"):
    g = g.sort_values("p"); a = g.iloc[0]; b = g.iloc[-1]
    print(f"load={ld:.2f} 峰值{a.peak_rate:4.1f}/min | 有效座率 {a.seat_effective_util*100:4.1f}%->{b.seat_effective_util*100:4.1f}% "
          f"(Δ{(b.seat_effective_util-a.seat_effective_util)*100:+5.1f}pp) | 产出 {a.seat_turnover_per_hour:.2f}->{b.seat_turnover_per_hour:.2f} "
          f"({(b.seat_turnover_per_hour/a.seat_turnover_per_hour-1)*100:+6.1f}%) | 流失 {a.abandon_ratio*100:4.1f}%->{b.abandon_ratio*100:4.1f}% "
          f"| 找座等 {a.seat_wait_mean:4.1f}->{b.seat_wait_mean:4.1f} | 打饭等 {a.food_wait_mean:4.2f}->{b.food_wait_mean:4.2f}")

show("E3 座位供给 x 占座比例 (繁忙日)")
d = pd.read_csv("results/e3_seats_p.csv")
for k, name in (("eff", "有效座位使用率(%)"), ("ab", "未落座流失率(%)"),
                ("turn", "座位产出(人次/座位/小时)")):
    m = d.pivot_table(index="n_seats", columns="p", values=k)
    if k != "turn":
        m = m * 100
    print(f"\n{name}\n", m.round(1 if k != 'turn' else 2))

show("E5 座位时间预算 (繁忙日, 占座位总容量 %)")
print(pd.read_csv("results/e5_budget.csv").round(2).to_string(index=False))

show("E6 管理干预方案对比 (繁忙日)")
d = pd.read_csv("results/e6_interventions.csv")
base = d.iloc[0]
for _, r in d.iterrows():
    tag = "现状" if _ == 0 else "对比"
    print(f"  {r.plan:22s} 有效{r.seat_effective_util*100:5.1f}% 产出 {r.seat_turnover_per_hour:.2f} "
          f"({(r.seat_turnover_per_hour/base.seat_turnover_per_hour-1)*100:+6.1f}%) 服务 {r.served:6.0f} "
          f"({(r.served/base.served-1)*100:+6.1f}%) 流失 {r.abandon_ratio*100:5.1f}% "
          f"找座 {r.seat_wait_mean:5.2f} 打饭 {r.food_wait_mean:5.2f} 平均在店 {r.total_time_mean:5.2f}")

show("E7 内生占座: 个体收益 vs 社会损失")
d = pd.read_csv("results/e7_endogenous_input.csv")
print(d.round(3).to_string(index=False))
print("\n复制者动态路径:\n", pd.read_csv("results/e7_endogenous_path.csv").round(3).to_string(index=False))

show("E8 行为变体稳健性 (繁忙日, 人数口径已对齐)")
d = pd.read_csv("results/e8_behavior_variants.csv")
print(d[["variant", "p", "seat_effective_util", "seat_turnover_per_hour", "abandon_ratio",
         "seat_wait_mean", "food_wait_mean", "people_served", "pre_claimed_share"]]
      .round(3).to_string(index=False))

show("E9 耐心敏感性 (繁忙日)")
d = pd.read_csv("results/e9_patience.csv")
lab = {6.0: "6min", 10.0: "10min", 15.0: "15min", 25.0: "25min", 999.0: "无限"}
for k in ("served_rate", "abandon_ratio", "seat_wait_mean", "seat_effective_util",
          "seat_effective_util_w2", "seat_idle_pre_util", "seat_turnover_per_hour",
          "spill_ratio", "food_wait_mean"):
    print(f"\n## {k}\n", d.pivot_table(index="cap", columns="p", values=k).rename(index=lab).round(4).to_string())
