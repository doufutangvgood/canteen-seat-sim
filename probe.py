# -*- coding: utf-8 -*-
"""探针: 硬核占座下 客流强度 x 占座比例。"""
from model import Config, run_once

SS = list(range(301, 311))
keys = ("seat_effective_util", "pk_effective_util", "seat_nominal_util", "seat_idle_pre_util",
        "pre_claimed_share", "seat_turnover_per_hour", "food_wait_mean", "seat_wait_mean",
        "wait_person_min_per_head", "served", "abandon_seat", "abandon_ratio")

for load in (0.9, 1.0, 1.1, 1.2):
    print(f"===== load={load} (峰值到达 {24*load:.1f}/min), 200座 8窗口 硬核占座 =====")
    for p in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        cfg = Config().copy(load_scale=load, adaptive_seat_first=False, p_seat_first=p)
        rows = [run_once(cfg, s) for s in SS]
        m = {k: sum(r[k] for r in rows) / len(rows) for k in keys}
        print(f"  p={p:.1f} 有效{m['seat_effective_util']:.3f} 高峰有效{m['pk_effective_util']:.3f} "
              f"名义{m['seat_nominal_util']:.3f} 空转{m['seat_idle_pre_util']:.4f} "
              f"实占{m['pre_claimed_share']:.2f} 产出{m['seat_turnover_per_hour']:.2f} | "
              f"打饭等{m['food_wait_mean']:5.2f} 找座等{m['seat_wait_mean']:5.2f} "
              f"人均等待{m['wait_person_min_per_head']:5.2f} | 服务{m['served']:5.0f} "
              f"流失{m['abandon_seat']:4.0f}({m['abandon_ratio']*100:4.1f}%)")
    print()
