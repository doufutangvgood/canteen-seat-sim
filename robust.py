# -*- coding: utf-8 -*-
"""稳健性检验: 加打饭窗口在座位瓶颈下是否真的无效/有害; 是否受"耐心上限"设定驱动。"""
from model import Config, run_once
import numpy as np

SS = list(range(4001, 4025))
BUSY = Config().copy(load_scale=1.15)

def m(cfg, k):
    a = np.array([run_once(cfg, s)[k] for s in SS])
    return a.mean(), 1.96 * a.std(ddof=1) / np.sqrt(len(a))

print("加窗口效果 x 学生耐心上限 (繁忙日, 200 座)")
print(f"{'耐心上限':>8} {'p':>4} {'窗口':>4} | {'服务人次':>18} {'流失率':>8} {'找座等待':>8} {'打饭等待':>8}")
for cap in (8.0, 15.0, 30.0, 999.0):
    for p in (0.0, 0.4):
        for w in (8, 11):
            cfg = BUSY.copy(p_seat_first=p, n_windows=w, max_seat_wait_min=cap)
            s, s_ci = m(cfg, "served")
            ab, _ = m(cfg, "abandon_ratio")
            sw, _ = m(cfg, "seat_wait_mean")
            fw, _ = m(cfg, "food_wait_mean")
            print(f"{cap:>8.0f} {p:>4.1f} {w:>4d} | {s:>10.0f} ± {s_ci:>5.0f} "
                  f"{ab*100:>7.1f}% {sw:>8.2f} {fw:>8.2f}")
    print()
