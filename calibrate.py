# -*- coding: utf-8 -*-
"""参数校准: 检查基准场景的指标量级是否贴近真实食堂。"""
import sys, time
from model import Config, run_once

base = Config()
ss = [101, 102, 103, 104, 105]

for p in (0.0, 0.5, 1.0):
    cfg = base.copy(p_seat_first=p)
    rows = [run_once(cfg, s) for s in ss]
    n_arr = sum(r["arrivals"] for r in rows) / len(rows)
    print(f"--- p={p:.1f}  平均到达 {n_arr:.0f} 人 ---")
    for k in ("seat_effective_util", "seat_nominal_util", "seat_idle_util", "seat_clean_util",
              "seat_free_util", "seat_waste_ratio", "seat_turnover_per_hour",
              "food_wait_mean", "food_wait_p95", "seat_wait_mean", "seat_wait_p95",
              "total_time_mean", "served", "balk_food", "abandon_seat", "full_house_ratio"):
        v = sum(r[k] for r in rows) / len(rows)
        print(f"    {k:26s} {v:9.3f}")
    print()
