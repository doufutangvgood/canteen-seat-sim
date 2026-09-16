# -*- coding: utf-8 -*-
"""
食堂"先占座再排队打饭"行为仿真模型
=====================================

问题
----
学生到达食堂后有两条可选路径:

    A. 先占座 (seat-first):  到达 -> 找/占座位 -> 排队打饭 -> 端饭回座 -> 吃饭 -> 离开
    B. 先排队 (queue-first): 到达 -> 排队打饭 -> 端着饭找座 -> 吃饭 -> 离开

路径 A 的座位从"占座成功"那一刻起就被占住, 但持有人在排队打饭, 座位处于
"被占住却未产出"的状态。本模型量化这一行为对**座位有效使用率**的影响。

核心口径
--------
   名义占用率 (nominal)  = 座位"被占住"的总时长 / (座位数 x 营业时长)
   有效使用率 (effective)= 座位上"确实在吃饭"的总时长 / (座位数 x 营业时长)
   座位空转率 (idle)     = 名义 - 有效          <- 占座行为的直接代价

   座位产出率 = 每个座位每小时服务的人次

实现方式
--------
离散事件仿真 (event-driven DES), 时间单位 = 分钟, 事件堆 heapq。
随机源拆分为独立子流 (到达 / 窗口服务 / 吃饭时长 / 策略选择 / 同行人数),
以便做共同随机数 (CRN) 对照实验。
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# --------------------------------------------------------------------------
# 参数配置
# --------------------------------------------------------------------------
@dataclass
class Config:
    # ---- 供给侧 ----
    n_seats: int = 200                 # 座位数
    n_windows: int = 8                 # 打饭窗口数
    cleanup_min: float = 0.40          # 收残/清台时间 (清台期间座位不可用)
    walk_seat_min: float = 0.45        # 找到座位并走过去的时间
    walk_tray_min: float = 0.45        # 端着饭走到座位的时间

    # ---- 需求侧 ----
    horizon_min: float = 90.0          # 营业时长 (11:20-12:50)
    arrival_peak_min: float = 30.0     # 客流峰值时刻 (相对开店)
    arrival_sigma_min: float = 18.0    # 客流峰宽度
    arrival_peak_rate: float = 24.0    # 峰值到达率 (人/分钟)
    load_scale: float = 1.0            # 客流强度整体缩放系数
    group_probs: Tuple[Tuple[int, float], ...] = ((1, 1.0),)   # 同行人数分布

    # ---- 服务时间 ----
    service_mean_min: float = 0.42     # 单窗口平均打饭时长 (约 25 秒)
    service_cv: float = 0.40           # 打饭时长变异系数
    eat_mean_min: float = 14.0         # 平均用餐时长
    eat_cv: float = 0.30               # 用餐时长变异系数

    # ---- 行为 ----
    p_seat_first: float = 0.0          # 先占座的学生比例 (核心自变量)
    adaptive_seat_first: bool = False  # 占不到座时是否退回"先排队"
    allow_seat_skip: bool = False      # 空位不足一组时, 是否允许后面的散客先坐
    seat_priority: str = "fifo"        # fifo | tray_first | seat_first

    # ---- 流失 (不耐烦) ----
    max_food_wait_min: float = 30.0    # 打饭排队超过此值 -> 走人
    max_seat_wait_min: float = 15.0    # 等座超过此值 -> 走人

    # ---- 记录 ----
    sample_interval_min: float = 0.5
    drain_window_min: float = 45.0     # 长窗口口径: 营业结束后继续统计的时长

    def copy(self, **kw) -> "Config":
        d = asdict(self)
        d.update(kw)
        return Config(**d)


# --------------------------------------------------------------------------
# 个体
# --------------------------------------------------------------------------
class Student:
    __slots__ = (
        "sid", "n_seats", "group", "seat_first", "pre_claimed",
        "t_arrive", "t_want_seat", "t_claim", "t_food_join", "t_food_start",
        "t_food_end", "t_eat_start", "t_eat_end", "t_leave",
        "state", "outcome", "cancelled",
    )

    def __init__(self, sid: int, n_seats: int, group: int, seat_first: bool, t_arrive: float):
        self.sid = sid
        self.n_seats = n_seats
        self.group = group
        self.seat_first = seat_first
        self.pre_claimed = False        # 是否成功"先占座"
        self.t_arrive = t_arrive
        self.t_want_seat: Optional[float] = None
        self.t_claim: Optional[float] = None
        self.t_food_join: Optional[float] = None
        self.t_food_start: Optional[float] = None
        self.t_food_end: Optional[float] = None
        self.t_eat_start: Optional[float] = None
        self.t_eat_end: Optional[float] = None
        self.t_leave: Optional[float] = None
        self.state = "new"
        self.outcome = "served"     # served | balk_food | abandon_seat
        self.cancelled = False


def _lognormal_params(mean: float, cv: float) -> Tuple[float, float]:
    """由均值与变异系数求 lognormal 参数。"""
    sigma2 = math.log(1.0 + cv * cv)
    mu = math.log(mean) - 0.5 * sigma2
    return mu, math.sqrt(sigma2)


def _overlap(a: Optional[float], b: Optional[float], lo: float, hi: float) -> float:
    """区间 [a,b] 与 [lo,hi] 的交集长度。"""
    if a is None or b is None:
        return 0.0
    return max(0.0, min(b, hi) - max(a, lo))


# --------------------------------------------------------------------------
# 仿真主体
# --------------------------------------------------------------------------
class CanteenSim:
    """一次仿真运行。"""

    def __init__(self, cfg: Config, seed: int):
        self.cfg = cfg
        self.seed = seed

        # 独立随机流: CRN 对照实验的基础
        ss = np.random.SeedSequence(seed)
        c = ss.spawn(5)
        self.rng_arr = np.random.default_rng(c[0])
        self.rng_srv = np.random.default_rng(c[1])
        self.rng_eat = np.random.default_rng(c[2])
        self.rng_cho = np.random.default_rng(c[3])
        self.rng_grp = np.random.default_rng(c[4])

        self._mu_srv, self._sg_srv = _lognormal_params(cfg.service_mean_min, cfg.service_cv)
        self._mu_eat, self._sg_eat = _lognormal_params(cfg.eat_mean_min, cfg.eat_cv)

        # 资源
        self.seats_free = cfg.n_seats
        self.free_windows = cfg.n_windows
        self.food_queue: deque[Student] = deque()
        self.seat_waiters: List[Student] = []   # 先占座但暂时没座
        self.tray_waiters: List[Student] = []   # 端着盘子等座

        # 计数
        self.n_claimed = 0      # 已被个人占住的座位数
        self.n_eating = 0       # 正在吃饭的人数
        self.n_cleaning = 0     # 清台中座位数

        # 事件堆
        self._ev = []
        self._cnt = itertools.count()
        self.students: List[Student] = []
        self.t = 0.0

        # 时间序列
        self.ts_t: List[float] = []
        self.ts_eating: List[int] = []
        self.ts_idle_hold: List[int] = []
        self.ts_cleaning: List[int] = []
        self.ts_free: List[int] = []
        self.ts_tray_wait: List[int] = []
        self.ts_seat_wait: List[int] = []
        self.ts_food_queue: List[int] = []

        # 统计
        self.stat = dict(
            arrivals=0, served=0, balk_food=0, abandon_seat=0,
            blocked_by_group_time=0.0,   # 有空位但因同行人数凑不齐而无法落座的时间
            full_house_time=0.0,         # 座位全满的时间
            horizon=cfg.horizon_min,
        )

    # ---------------- 事件堆 ----------------
    def push(self, t: float, kind: str, *payload):
        heapq.heappush(self._ev, (t, next(self._cnt), kind, payload))

    # ---------------- 需求生成 ----------------
    def _generate_arrivals(self) -> List[Tuple[float, int]]:
        cfg = self.cfg
        lam_max = cfg.arrival_peak_rate * cfg.load_scale * 1.05
        out: List[Tuple[float, int]] = []
        sizes = [s for s, _ in cfg.group_probs]
        probs = np.array([p for _, p in cfg.group_probs], dtype=float)
        probs = probs / probs.sum()
        t = 0.0
        while True:
            t += self.rng_arr.exponential(1.0 / lam_max)
            if t > cfg.horizon_min:
                break
            lam = (cfg.arrival_peak_rate * cfg.load_scale
                   * math.exp(-0.5 * ((t - cfg.arrival_peak_min) / cfg.arrival_sigma_min) ** 2))
            if self.rng_arr.random() < lam / lam_max:
                g = int(self.rng_grp.choice(sizes, p=probs))
                out.append((t, g))
        return out

    def _draw_service(self) -> float:
        return float(self.rng_srv.lognormal(self._mu_srv, self._sg_srv))

    def _draw_eat(self) -> float:
        return float(self.rng_eat.lognormal(self._mu_eat, self._sg_eat))

    # ---------------- 座位分配 ----------------
    def _pick_waiter(self) -> Optional[Tuple[Student, str]]:
        """按策略从两个等待池中选出下一个可落座的人。"""
        if not self.seat_waiters and not self.tray_waiters:
            return None
        pol = self.cfg.seat_priority
        if pol == "tray_first" and self.tray_waiters:
            pool, tag = self.tray_waiters, "tray"
        elif pol == "seat_first" and self.seat_waiters:
            pool, tag = self.seat_waiters, "seat"
        else:
            cand = []
            if self.seat_waiters:
                cand.append((min(s.t_want_seat for s in self.seat_waiters), "seat"))
            if self.tray_waiters:
                cand.append((min(s.t_want_seat for s in self.tray_waiters), "tray"))
            _, tag = min(cand)
            pool = self.seat_waiters if tag == "seat" else self.tray_waiters
        st = min(pool, key=lambda s: s.t_want_seat)
        return st, tag

    def _allocate(self):
        """把空座位分配给等待者 (严格先到先得; 组内需连坐)。"""
        while True:
            if self.seats_free <= 0:
                break
            picked = self._pick_waiter()
            if picked is None:
                break
            st, tag = picked
            if st.n_seats > self.seats_free:
                # 队首的一组坐不下 -> 空位被"锁死", 记录这段低效时间
                if self.cfg.allow_seat_skip:
                    # 允许后面的散客先坐: 换一个人尝试
                    alt = self._pick_waiter_skipping(st)
                    if alt is None:
                        break
                    st, tag = alt
                    if st.n_seats > self.seats_free:
                        break
                else:
                    self.stat["blocked_by_group_time"] += 0.0  # 时长在采样时累计
                    break
            # 落座
            pool = self.seat_waiters if tag == "seat" else self.tray_waiters
            pool.remove(st)
            self.seats_free -= st.n_seats
            self.n_claimed += st.n_seats
            st.t_claim = self.t
            if tag == "seat":
                # 先占座的人: 座位已占, 现在去排队打饭
                st.state = "holding"
                st.pre_claimed = True
                self._enqueue_food(st)
            else:
                # 端盘等待的人: 走到座位开始吃饭
                st.state = "walking"
                self.push(self.t + self.cfg.walk_tray_min, "EAT_START", st)

    def _pick_waiter_skipping(self, blocked: Student) -> Optional[Tuple[Student, str]]:
        """allow_seat_skip=True 时, 找一个能坐下的后来者。"""
        cand = []
        for s in self.seat_waiters:
            if s is not blocked and s.n_seats <= self.seats_free:
                cand.append((s.t_want_seat, s, "seat"))
        for s in self.tray_waiters:
            if s is not blocked and s.n_seats <= self.seats_free:
                cand.append((s.t_want_seat, s, "tray"))
        if not cand:
            return None
        _, s, tag = min(cand, key=lambda x: x[0])
        return s, tag

    # ---------------- 打饭队列 ----------------
    def _enqueue_food(self, st: Student):
        st.t_food_join = self.t
        st.state = "queuing"
        self.food_queue.append(st)
        if self.cfg.max_food_wait_min < 1e9:
            self.push(self.t + self.cfg.max_food_wait_min, "BALK_FOOD", st)
        self._start_services()

    def _start_services(self):
        while self.free_windows > 0 and self.food_queue:
            st = self.food_queue.popleft()
            if st.cancelled:
                continue
            self.free_windows -= 1
            st.t_food_start = self.t
            st.state = "serving"
            self.push(self.t + self._draw_service(), "SERVICE_DONE", st)

    # ---------------- 事件处理 ----------------
    def _on_arrive(self, st: Student):
        self.stat["arrivals"] += 1
        if st.seat_first:
            st.t_want_seat = self.t
            st.state = "wait_seat"
            self.seat_waiters.append(st)
            if self.cfg.max_seat_wait_min < 1e9:
                self.push(self.t + self.cfg.max_seat_wait_min, "ABANDON_SEAT", st)
            self._allocate()
            if st.state == "wait_seat" and self.cfg.adaptive_seat_first:
                # 占不到座 -> 退回"先排队后找座", 身份随之转变
                self.seat_waiters.remove(st)
                st.seat_first = False
                st.t_want_seat = None
                st.state = "new"
                self._enqueue_food(st)
        else:
            self._enqueue_food(st)

    def _on_service_done(self, st: Student):
        self.free_windows += 1
        st.t_food_end = self.t
        if st.seat_first:
            # 座位已占, 端饭回座
            st.state = "walking"
            self.push(self.t + self.cfg.walk_tray_min, "EAT_START", st)
        else:
            # 端着饭找座
            st.t_want_seat = self.t
            st.state = "wait_tray"
            self.tray_waiters.append(st)
            if self.cfg.max_seat_wait_min < 1e9:
                self.push(self.t + self.cfg.max_seat_wait_min, "ABANDON_SEAT", st)
            self._allocate()
        self._start_services()

    def _on_eat_start(self, st: Student):
        st.t_eat_start = self.t
        st.t_eat_end = self.t + self._draw_eat()
        st.state = "eating"
        self.n_eating += st.n_seats
        self.push(st.t_eat_end, "EAT_DONE", st)

    def _on_eat_done(self, st: Student):
        self.n_eating -= st.n_seats
        self.n_claimed -= st.n_seats
        st.t_leave = self.t
        st.state = "done"
        self.n_cleaning += st.n_seats
        self.push(self.t + self.cfg.cleanup_min, "CLEAN_DONE", st)

    def _on_clean_done(self, st: Student):
        self.n_cleaning -= st.n_seats
        self.seats_free += st.n_seats
        self._allocate()

    def _on_balk_food(self, st: Student):
        if st.state != "queuing":
            return
        st.cancelled = True
        st.outcome = "balk_food"
        st.state = "left"
        st.t_leave = self.t
        self.stat["balk_food"] += 1
        if st.t_claim is not None:      # 占了座又走人 -> 立刻释放
            self.n_claimed -= st.n_seats
            self.seats_free += st.n_seats
            st.t_leave = self.t
            self._allocate()

    def _on_abandon_seat(self, st: Student):
        if st.state == "wait_seat":
            self.seat_waiters.remove(st)
        elif st.state == "wait_tray":
            self.tray_waiters.remove(st)
        else:
            return
        st.outcome = "abandon_seat"
        st.state = "left"
        st.t_leave = self.t
        self.stat["abandon_seat"] += 1

    def _sample(self):
        self.ts_t.append(self.t)
        self.ts_eating.append(self.n_eating)
        self.ts_idle_hold.append(max(0, self.n_claimed - self.n_eating))
        self.ts_cleaning.append(self.n_cleaning)
        self.ts_free.append(self.seats_free)
        self.ts_tray_wait.append(len(self.tray_waiters))
        self.ts_seat_wait.append(len(self.seat_waiters))
        self.ts_food_queue.append(len(self.food_queue))
        if self.seats_free == 0:
            self.stat["full_house_time"] += self.cfg.sample_interval_min
        elif self.seat_waiters or self.tray_waiters:
            self.stat["blocked_by_group_time"] += self.cfg.sample_interval_min

    # ---------------- 主循环 ----------------
    def run(self) -> Dict:
        cfg = self.cfg
        arrivals = self._generate_arrivals()
        for i, (t, g) in enumerate(arrivals):
            seat_first = bool(self.rng_cho.random() < cfg.p_seat_first)
            st = Student(i, g, g, seat_first, t)
            self.students.append(st)
            self.push(t, "ARRIVE", st)

        t = cfg.sample_interval_min
        while t <= cfg.horizon_min:
            self.push(t, "SAMPLE")
            t += cfg.sample_interval_min

        # 主循环: 到达结束后继续推进以排空系统 (统计等待时长需要)
        drain_end = cfg.horizon_min + 180.0
        while self._ev:
            t, _, kind, payload = heapq.heappop(self._ev)
            if t > drain_end:
                break
            self.t = t
            if kind == "ARRIVE":
                self._on_arrive(payload[0])
            elif kind == "SERVICE_DONE":
                self._on_service_done(payload[0])
            elif kind == "EAT_START":
                self._on_eat_start(payload[0])
            elif kind == "EAT_DONE":
                self._on_eat_done(payload[0])
            elif kind == "CLEAN_DONE":
                self._on_clean_done(payload[0])
            elif kind == "BALK_FOOD":
                self._on_balk_food(payload[0])
            elif kind == "ABANDON_SEAT":
                self._on_abandon_seat(payload[0])
            elif kind == "SAMPLE":
                self._sample()

        return self._collect()

    # ---------------- 指标汇总 ----------------
    def _collect(self) -> Dict:
        cfg = self.cfg
        H = cfg.horizon_min
        cap = cfg.n_seats * H                     # 座位分钟总量
        # 高峰窗口 (峰值前后), 用于避开"全时段平均"对拥堵的稀释
        pk0 = max(0.0, cfg.arrival_peak_min - 20.0)
        pk1 = min(H, cfg.arrival_peak_min + 30.0)
        pkH = pk1 - pk0
        cap_pk = cfg.n_seats * pkH
        # 长窗口: 覆盖"营业结束后仍在吃饭"的人, 用于剔除窗口截断的影响
        H2 = H + cfg.drain_window_min
        cap2 = cfg.n_seats * H2

        tot = dict(nom=0.0, eat=0.0, idle_pre=0.0, idle_walk=0.0, clean=0.0)
        pk = dict(nom=0.0, eat=0.0, idle_pre=0.0, idle_walk=0.0)
        w2 = dict(nom=0.0, eat=0.0, idle_pre=0.0, idle_walk=0.0)
        n_spill = 0
        food_waits, seat_waits_all, seat_waits_srv = [], [], []
        tray_waits_all, sf_seatwaits = [], []
        totals, sf_total, qf_total = [], [], []
        wait_person_min = 0.0
        served = 0
        n_pre = 0
        n_instant = 0

        for st in self.students:
            n = st.n_seats
            if st.pre_claimed:
                n_pre += 1
                if st.t_claim - st.t_arrive <= 1e-6:
                    n_instant += 1
            # 先占座者: 占座 -> 坐下吃饭 之间的空转 (排队 + 打饭 + 走回)
            # 端盘找座者: 落座 -> 坐下吃饭 (走路)
            i0, i1 = st.t_claim, st.t_eat_start
            hold_iv = (st.t_claim, st.t_leave)
            eat_iv = (st.t_eat_start, st.t_eat_end)
            clean_iv = (st.t_eat_end, st.t_eat_end + cfg.cleanup_min if st.t_eat_end else None)

            for d, lo, hi in ((tot, 0.0, H), (pk, pk0, pk1), (w2, 0.0, H2)):
                h = _overlap(hold_iv[0], hold_iv[1], lo, hi)
                e = _overlap(eat_iv[0], eat_iv[1], lo, hi)
                g = _overlap(i0, i1, lo, hi)
                d["nom"] += n * h
                d["eat"] += n * e
                if st.pre_claimed:
                    d["idle_pre"] += n * g
                else:
                    d["idle_walk"] += n * g
                if d is tot:
                    tot["clean"] += n * _overlap(clean_iv[0], clean_iv[1], lo, hi)
            if st.t_eat_end is not None and st.t_eat_end > H:
                n_spill += 1

            if st.outcome == "served":
                served += 1
                if st.t_food_start is not None:
                    fw = st.t_food_start - st.t_food_join
                    food_waits.append(fw)
                    wait_person_min += fw * n
                if st.t_claim is not None and st.t_want_seat is not None:
                    sw = st.t_claim - st.t_want_seat
                    seat_waits_srv.append(sw)
                    seat_waits_all.append(sw)
                    (sf_seatwaits if st.pre_claimed else tray_waits_all).append(sw)
                if st.t_leave is not None:
                    totals.append(st.t_leave - st.t_arrive)
                    (sf_total if st.pre_claimed else qf_total).append(st.t_leave - st.t_arrive)
            else:
                # 中途放弃者: 等待时长按"截尾"计入, 避免幸存者偏差
                if st.t_want_seat is not None and st.t_leave is not None:
                    sw = st.t_leave - st.t_want_seat
                    seat_waits_all.append(sw)
                    wait_person_min += sw * n

        def stat(arr):
            if not arr:
                return dict(mean=float("nan"), p50=float("nan"), p95=float("nan"), max=float("nan"))
            a = np.asarray(arr, dtype=float)
            return dict(mean=float(a.mean()), p50=float(np.percentile(a, 50)),
                        p95=float(np.percentile(a, 95)), max=float(a.max()))

        nom_util = tot["nom"] / cap
        # 按"人"统一口径 (结伴场景下一次到达代表 g 个人)
        people_arrived = sum(st.n_seats for st in self.students)
        people_served = sum(st.n_seats for st in self.students if st.outcome == "served")
        res = dict(
            seed=self.seed,
            p_seat_first=cfg.p_seat_first,
            load_scale=cfg.load_scale,
            n_seats=cfg.n_seats,
            n_windows=cfg.n_windows,
            arrivals=self.stat["arrivals"],
            served=served,
            balk_food=self.stat["balk_food"],
            abandon_seat=self.stat["abandon_seat"],
            abandon_ratio=(people_arrived - people_served) / max(1, people_arrived),
            people_arrived=people_arrived,
            people_served=people_served,
            pre_claimed_share=n_pre / max(1, self.stat["arrivals"]),
            instant_claim_share=n_instant / max(1, self.stat["arrivals"]),
            # --- 座位口径: 全时段 ---
            seat_effective_util=tot["eat"] / cap,
            seat_nominal_util=nom_util,
            seat_idle_util=(tot["idle_pre"] + tot["idle_walk"]) / cap,
            seat_idle_pre_util=tot["idle_pre"] / cap,     # 先占座导致的空转
            seat_idle_walk_util=tot["idle_walk"] / cap,   # 走路落座
            seat_clean_util=tot["clean"] / cap,
            seat_free_util=max(0.0, 1.0 - nom_util - tot["clean"] / cap),
            seat_waste_ratio=(tot["idle_pre"] / tot["nom"]) if tot["nom"] > 0 else float("nan"),
            seat_turnover_per_hour=people_served / cfg.n_seats / (H / 60.0),
            # --- 座位口径: 高峰窗口 ---
            pk_effective_util=pk["eat"] / cap_pk,
            pk_nominal_util=pk["nom"] / cap_pk,
            pk_idle_pre_util=pk["idle_pre"] / cap_pk,
            pk_free_util=max(0.0, 1.0 - pk["nom"] / cap_pk),
            # --- 座位口径: 长窗口 (营业+45分钟, 剔除窗口截断) ---
            seat_effective_util_w2=w2["eat"] / cap2,
            seat_nominal_util_w2=w2["nom"] / cap2,
            seat_idle_pre_util_w2=w2["idle_pre"] / cap2,
            spill_ratio=n_spill / max(1, self.stat["arrivals"]),
            served_rate=people_served / max(1, people_arrived),
            full_house_ratio=self.stat["full_house_time"] / H,
            group_blocked_ratio=self.stat["blocked_by_group_time"] / H,
            # --- 等待口径 ---
            food_wait_mean=stat(food_waits)["mean"],
            food_wait_p95=stat(food_waits)["p95"],
            seat_wait_mean=stat(seat_waits_all)["mean"],
            seat_wait_p95=stat(seat_waits_all)["p95"],
            seat_wait_served_mean=stat(seat_waits_srv)["mean"],
            tray_wait_mean=stat(tray_waits_all)["mean"],
            sf_seat_wait_mean=stat(sf_seatwaits)["mean"],
            total_time_mean=stat(totals)["mean"],
            total_time_p95=stat(totals)["p95"],
            sf_total_mean=stat(sf_total)["mean"],
            qf_total_mean=stat(qf_total)["mean"],
            wait_person_min=wait_person_min,        # 全体学生等待总人·分钟
            wait_person_min_per_head=wait_person_min / max(1, self.stat["arrivals"]),
            # --- 时间序列 ---
            ts=dict(t=self.ts_t, eating=self.ts_eating, idle_hold=self.ts_idle_hold,
                    cleaning=self.ts_cleaning, free=self.ts_free,
                    tray_wait=self.ts_tray_wait, seat_wait=self.ts_seat_wait,
                    food_queue=self.ts_food_queue),
        )
        return res


def run_once(cfg: Config, seed: int) -> Dict:
    return CanteenSim(cfg, seed).run()
