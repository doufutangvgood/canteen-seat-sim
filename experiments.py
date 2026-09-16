# -*- coding: utf-8 -*-
"""
食堂占座仿真 —— 实验与出图
==========================
E1 占座比例 p 扫描 (基准日 / 繁忙日)
E2 p x 客流强度 相图
E3 座位供给 x 占座比例
E4 高峰日时间序列对比
E5 座位时间预算分解
E6 管理干预方案对比
E7 占座行为内生化的"囚徒困境"分析
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from model import Config, run_once

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
FIG = os.path.join(HERE, "figures")
os.makedirs(RES, exist_ok=True)
os.makedirs(FIG, exist_ok=True)

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 130,
    "savefig.dpi": 130,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.titlesize": 11.5,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "figure.facecolor": "white",
})

SEEDS = list(range(1001, 1025))          # 24 次重复, 同一组种子 = 共同随机数(CRN)
SEEDS_S = list(range(2001, 2011))        # 10 次重复, 用于二维扫描

BASE = Config()
# 基准日: 峰值 24 人/分, 全天约 1030 人, 200 座, 8 窗口
# 繁忙日: 峰值 27.6 人/分 (load=1.15), 全天约 1180 人
BUSY = Config().copy(load_scale=1.15)


# ---------------------------------------------------------------- 工具
def bench(cfg, seeds=SEEDS):
    rows = [run_once(cfg, s) for s in seeds]
    keep = {k: v for k, v in rows[0].items() if k != "ts"}
    out = {}
    for k in keep:
        a = np.array([r[k] for r in rows], dtype=float)
        out[k] = a.mean()
        out[k + "_ci"] = 1.96 * a.std(ddof=1) / np.sqrt(len(a))
    out["_rows"] = rows
    return out


def sweep_p(cfg, ps, seeds=SEEDS):
    recs = []
    for p in ps:
        m = bench(cfg.copy(p_seat_first=float(p)), seeds)
        m["p"] = p
        recs.append(m)
    return recs


def to_df(recs, cols=None):
    cols = cols or [k for k in recs[0] if not k.startswith("_")]
    return pd.DataFrame([{k: r[k] for k in cols} for r in recs])


def band(ax, x, y, ci, **kw):
    ax.plot(x, y, **kw)
    ax.fill_between(x, np.array(y) - np.array(ci), np.array(y) + np.array(ci),
                    alpha=0.18, linewidth=0)


def check_legends(fig, tag):
    """质检: 图例框是否压住数据点/线。"""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    issues = []
    for i, ax in enumerate(fig.axes):
        leg = ax.get_legend()
        if leg is None:
            continue
        lb = leg.get_window_extent(r)
        hit = 0
        for ln in ax.get_lines():
            xy = ln.get_xydata()
            if len(xy) == 0:
                continue
            disp = ax.transData.transform(xy)
            inside = ((disp[:, 0] >= lb.x0) & (disp[:, 0] <= lb.x1) &
                      (disp[:, 1] >= lb.y0) & (disp[:, 1] <= lb.y1))
            hit += int(inside.sum())
        if hit:
            issues.append(f"axes[{i}] 图例压住 {hit} 个数据点")
    if issues:
        print(f"  [质检警告] {tag}: " + "; ".join(issues))
    else:
        print(f"  [质检通过] {tag}: 无图例遮挡")


# ================================================================ E1
def e1():
    ps = np.round(np.arange(0, 1.0001, 0.05), 2)
    store = {}
    for tag, cfg in (("base", BASE), ("busy", BUSY)):
        recs = sweep_p(cfg, ps)
        store[tag] = recs
        df = to_df(recs)
        df["scenario"] = tag
        df.to_csv(os.path.join(RES, f"e1_p_sweep_{tag}.csv"), index=False,
                  encoding="utf-8-sig")
        print(f"[E1:{tag}] 完成 -> results/e1_p_sweep_{tag}.csv")

    # ---- 图 1 ----
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.6))
    for tag, label, c in (("base", "基准日 (1000人/日)", "#1f77b4"),
                          ("busy", "繁忙日 (1180人/日)", "#d62728")):
        recs = store[tag]
        x = np.array([r["p"] for r in recs])
        g = lambda k: np.array([r[k] for r in recs])
        gc = lambda k: np.array([r[k + "_ci"] for r in recs])
        tag = label
        ax = axes[0, 0]
        band(ax, x, g("seat_effective_util") * 100, gc("seat_effective_util") * 100,
             color=c, label=f"有效使用率 · {tag}", marker="o", ms=3)
        ax.plot(x, g("pk_effective_util") * 100, color=c, ls="--", lw=1,
                label=f"高峰有效使用率 · {tag}")
        ax.plot(x, g("seat_nominal_util") * 100, color=c, ls=":", lw=1.2,
                label=f"名义占用率 · {tag}")
        ax.set_ylabel("占座位总容量的比例 (%)")
        ax.set_title("(a) 座位使用率：占座只抬高“占用”，压低“有效”")
        ax.legend(fontsize=7, loc="lower left", ncol=2, framealpha=0.92)
        ax.set_ylim(62, 96)

        ax = axes[0, 1]
        band(ax, x, g("seat_turnover_per_hour"), gc("seat_turnover_per_hour"),
             color=c, label=f"座位产出 · {tag}", marker="o", ms=3)
        ax.set_ylabel("人次 / 座位 / 小时")
        ax.set_title("(b) 座位产出率（每座位每小时服务人次）")
        ax.set_ylim(2.95, 3.95)
        ax.legend(fontsize=7.5, loc="lower left", framealpha=0.92)

        ax = axes[1, 0]
        band(ax, x, g("seat_wait_mean"), gc("seat_wait_mean"),
             color=c, label=f"找座等待 · {tag}", marker="o", ms=3)
        ax.set_ylabel("平均等待 (分钟)", color=c)
        ax.set_title("(c) 等座时间与流失率")
        ax.set_ylim(4.5, 13.5)
        ax2 = ax.twinx()
        ax2.plot(x, g("abandon_ratio") * 100, color=c, ls="--", marker="s", ms=3,
                 label=f"未落座流失率 · {tag}")
        ax2.set_ylabel("未落座流失率 (%)", color=c)
        ax2.set_ylim(0, 22)
        ax2.grid(False)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=6.6, loc="upper left", ncol=2,
                  framealpha=0.92)

        ax = axes[1, 1]
        band(ax, x, g("food_wait_mean"), gc("food_wait_mean"),
             color=c, label=f"打饭排队 · {tag}", marker="o", ms=3)
        ax.plot(x, g("seat_wait_mean"), color=c, ls="--", marker="s", ms=3,
                label=f"找座等待 · {tag}")
        ax.set_ylabel("平均等待 (分钟)")
        ax.set_title("(d) 拥堵转移：占座把排队从窗口搬到座位")
        ax.set_ylim(0, 12.5)
        ax.legend(fontsize=7, loc="upper right", ncol=2, framealpha=0.92)

    for ax in axes.ravel():
        ax.set_xlabel("先占座学生比例 p")
        ax.set_xlim(-0.02, 1.02)
    fig.suptitle("图1  先占座比例对食堂座位系统的边际影响（24 次重复，阴影 = 95% 置信区间）",
                 fontsize=12.5, y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    check_legends(fig, "图1")
    fig.savefig(os.path.join(FIG, "fig1_p_sweep.png"))
    plt.close(fig)
    print("[E1] 图1 完成")


# ================================================================ E2
def e2():
    loads = np.round(np.arange(0.85, 1.351, 0.05), 2)
    ps = np.round(np.arange(0, 1.0001, 0.1), 2)
    metrics = ["seat_effective_util", "seat_turnover_per_hour",
               "abandon_ratio", "seat_wait_mean", "food_wait_mean", "seat_idle_pre_util"]
    Z = {k: np.zeros((len(loads), len(ps))) for k in metrics}
    for i, ld in enumerate(loads):
        for j, p in enumerate(ps):
            m = bench(BASE.copy(load_scale=float(ld), p_seat_first=float(p)), SEEDS_S)
            for k in metrics:
                Z[k][i, j] = m[k]
    rows = []
    for i, ld in enumerate(loads):
        for j, p in enumerate(ps):
            rows.append(dict(load_scale=ld, peak_rate=24 * ld, p=p,
                             **{k: Z[k][i, j] for k in metrics}))
    pd.DataFrame(rows).to_csv(os.path.join(RES, "e2_load_p.csv"),
                              index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.0))
    specs = [("seat_effective_util", "(a) 有效座位使用率 (%)", 100, "YlGnBu", "{:.0f}"),
             ("seat_turnover_per_hour", "(b) 座位产出 (人次/座位/小时)", 1, "YlGnBu", "{:.2f}"),
             ("abandon_ratio", "(c) 未落座流失率 (%)", 100, "OrRd", "{:.1f}"),
             ("seat_wait_mean", "(d) 平均找座等待 (分钟)", 1, "OrRd", "{:.1f}")]
    for ax, (k, title, scale, cmap, fmt) in zip(axes.ravel(), specs):
        z = Z[k] * scale
        im = ax.pcolormesh(ps, loads, z, cmap=cmap, shading="auto")
        ax.set_title(title)
        ax.set_xlabel("先占座学生比例 p")
        ax.set_ylabel("客流强度 (峰值到达率倍数)")
        fig.colorbar(im, ax=ax)
        for i in range(len(loads)):
            for j in range(len(ps)):
                ax.text(ps[j], loads[i], fmt.format(z[i, j]), ha="center", va="center",
                        fontsize=5.4, color="black")
    fig.suptitle("图2  占座危害随客流强度非线性放大（200 座 / 8 窗口，10 次重复）",
                 fontsize=12.5, y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    check_legends(fig, "图2")
    fig.savefig(os.path.join(FIG, "fig2_load_surface.png"))
    plt.close(fig)
    print("[E2] 完成")


# ================================================================ E3
def e3():
    seats = [160, 175, 190, 200, 215, 230, 250]
    ps = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    recs = []
    for s in seats:
        for p in ps:
            m = bench(BUSY.copy(n_seats=s, p_seat_first=p), SEEDS_S)
            recs.append(dict(n_seats=s, p=p,
                             eff=m["seat_effective_util"], eff_ci=m["seat_effective_util_ci"],
                             turn=m["seat_turnover_per_hour"], ab=m["abandon_ratio"],
                             wait=m["seat_wait_mean"], served=m["served"]))
    df = pd.DataFrame(recs)
    df.to_csv(os.path.join(RES, "e3_seats_p.csv"), index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.9))
    colors = plt.cm.viridis(np.linspace(0.05, 0.9, len(ps)))
    for p, c in zip(ps, colors):
        d = df[df.p == p]
        axes[0].plot(d.n_seats, d.eff * 100, marker="o", ms=3.5, color=c, label=f"p={p:g}")
        axes[1].plot(d.n_seats, d.turn, marker="o", ms=3.5, color=c, label=f"p={p:g}")
        axes[2].plot(d.n_seats, d.ab * 100, marker="o", ms=3.5, color=c, label=f"p={p:g}")
    axes[0].set_title("(a) 有效座位使用率")
    axes[0].set_ylabel("%")
    axes[1].set_title("(b) 座位产出率")
    axes[1].set_ylabel("人次/座位/小时")
    axes[2].set_title("(c) 未落座流失率")
    axes[2].set_ylabel("%")
    for ax in axes:
        ax.set_xlabel("座位数")
        ax.legend(fontsize=7.5)
    fig.suptitle("图3  加座位能否抵消占座的损失？（繁忙日，10 次重复）", fontsize=12.5, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    check_legends(fig, "图3")
    fig.savefig(os.path.join(FIG, "fig3_seats_lever.png"))
    plt.close(fig)
    print("[E3] 完成")


# ================================================================ E4 + E5
def e4_e5():
    ps = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    ts_by_p, budget = {}, []
    for p in ps:
        rows = [run_once(BUSY.copy(p_seat_first=p), s) for s in SEEDS]
        ts_by_p[p] = rows
        keep = [k for k in rows[0] if k != "ts"]
        m = {k: float(np.mean([r[k] for r in rows])) for k in keep}
        budget.append(dict(
            p=p,
            eating=m["seat_effective_util"] * 100,
            idle_pre=m["seat_idle_pre_util"] * 100,
            idle_walk=m["seat_idle_walk_util"] * 100,
            cleaning=m["seat_clean_util"] * 100,
            free=m["seat_free_util"] * 100,
        ))
    pd.DataFrame(budget).to_csv(os.path.join(RES, "e5_budget.csv"),
                                index=False, encoding="utf-8-sig")

    # ---- 图5 座位时间预算 ----
    b = pd.DataFrame(budget)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2))
    cols = ["eating", "idle_pre", "idle_walk", "cleaning", "free"]
    names = ["有效使用（在吃饭）", "占座空转（占着去打饭）", "落座走动",
             "清台占用", "空闲"]
    csl = ["#2e7d32", "#d32f2f", "#ffb74d", "#90a4ae", "#e0e0e0"]
    ax = axes[0]
    ax.stackplot(b.p, *[b[c] for c in cols], labels=names, colors=csl, alpha=0.95)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 100)
    ax.set_title("座位时间预算（每 100 座位·分钟的去向）")
    ax.set_xlabel("先占座学生比例 p")
    ax.set_ylabel("占座位总容量的 %")
    ax.legend(fontsize=8, loc="lower left")
    ax = axes[1]
    ax.plot(b.p, b.free, marker="o", color="#546e7a", label="空闲座位")
    ax.plot(b.p, b.idle_pre, marker="s", color="#d32f2f", label="占座空转")
    ax.plot(b.p, b.eating, marker="^", color="#2e7d32", label="有效使用")
    # 右轴: 绝对座位分钟
    ax2 = ax.twinx()
    cap = BUSY.n_seats * BUSY.horizon_min
    ax2.plot(b.p, b.idle_pre / 100 * cap, ls="--", color="#d32f2f", lw=1)
    ax2.set_ylabel("占座空转的座位·分钟（虚线）")
    ax2.grid(False)
    ax.set_title("占座空转挤掉的是“有效使用”与“空闲缓冲”")
    ax.set_xlabel("先占座学生比例 p")
    ax.set_ylabel("占座位总容量的 %")
    ax.set_xlim(0, 1)
    ax.legend(fontsize=8)
    fig.suptitle("图5  座位时间都去哪了（繁忙日）", fontsize=12.5, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    check_legends(fig, "图5")
    fig.savefig(os.path.join(FIG, "fig5_budget.png"))
    plt.close(fig)

    # ---- 图4 时间序列 ----
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.2))
    cs = {0.0: "#2e7d32", 0.4: "#f9a825", 1.0: "#c62828"}
    def avg_ts(p, key):
        arrs = np.array([r["ts"][key] for r in ts_by_p[p]], dtype=float)
        return arrs.mean(axis=0)
    t = avg_ts(0.0, "t")
    panels = [("eating", "(a) 同时用餐人数", "人"),
              ("idle_hold", "(b) 被占住但无人用餐的座位数", "座"),
              ("food_queue", "(c) 打饭排队人数", "人"),
              ("tray_wait", "(d) 端着饭等座位的人数", "人")]
    for ax, (k, title, yl) in zip(axes.ravel(), panels):
        for p, c in cs.items():
            ax.plot(t, avg_ts(p, k), color=c, lw=1.8 if p == 0.4 else 1.2,
                    label=f"占座比例 p={p:g}")
        ax.set_title(title)
        ax.set_ylabel(yl)
        ax.set_xlabel("营业时间（分钟，0 = 开门）")
        ax.legend(fontsize=8)
    fig.suptitle("图4  繁忙日全天动态：占座如何改变拥堵的形态（24 次重复均值）",
                 fontsize=12.5, y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    check_legends(fig, "图4")
    fig.savefig(os.path.join(FIG, "fig4_timeseries.png"))
    plt.close(fig)
    print("[E4/E5] 完成")


# ================================================================ E6
def e6():
    plans = [
        ("现状\n(占座率 40%)", BUSY.copy(p_seat_first=0.4)),
        ("禁止占座\n(p = 0)", BUSY.copy(p_seat_first=0.0)),
        ("加 30 个座位\n(200→230)", BUSY.copy(p_seat_first=0.4, n_seats=230)),
        ("加 3 个窗口\n(8→11)", BUSY.copy(p_seat_first=0.4, n_windows=11)),
        ("加窗口 + 禁占座", BUSY.copy(p_seat_first=0.0, n_windows=11)),
        ("加座位 + 禁占座", BUSY.copy(p_seat_first=0.0, n_seats=230)),
    ]
    keys = ["seat_effective_util", "seat_turnover_per_hour", "abandon_ratio",
            "seat_wait_mean", "served", "food_wait_mean", "total_time_mean"]
    recs = []
    for name, cfg in plans:
        m = bench(cfg, SEEDS)
        recs.append(dict(plan=name.replace("\n", " "),
                         **{k: m[k] for k in keys}))
    df = pd.DataFrame(recs)
    df.to_csv(os.path.join(RES, "e6_interventions.csv"), index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    x = np.arange(len(df))
    base = df.iloc[0]
    for ax, (k, title, fmt, yl) in zip(axes, [
            ("seat_turnover_per_hour", "(a) 座位产出率", "{:.2f}", "人次/座位/小时"),
            ("abandon_ratio", "(b) 未落座流失率", "{:.1%}", "%"),
            ("seat_wait_mean", "(c) 平均找座等待", "{:.1f}", "分钟")]):
        v = df[k].values * (100 if k == "abandon_ratio" else 1)
        b0 = (base[k] * 100 if k == "abandon_ratio" else base[k])
        cols = ["#9e9e9e"] + ["#2e7d32" if (v[i] - b0) * (1 if k != "abandon_ratio" else -1) > 0
                              else "#c62828" for i in range(1, len(v))]
        ax.bar(x, v, color=cols)
        ax.axhline(b0, color="#37474f", ls="--", lw=1, label="现状")
        ax.set_title(title)
        ax.set_ylabel(yl)
        ax.set_xticks(x)
        ax.set_xticklabels([n.replace(" ", "\n") for n in df.plan], fontsize=7.5)
        if k == "abandon_ratio":
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda t, _: f"{t:.0f}%"))
        for i, val in enumerate(v):
            ax.text(i, val, fmt.format(val if k != "abandon_ratio" else val / 100),
                    ha="center", va="bottom", fontsize=7.5)
    axes[0].legend(fontsize=8)
    fig.suptitle("图6  六种治理方案对比（繁忙日，24 次重复）", fontsize=12.5, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    check_legends(fig, "图6")
    fig.savefig(os.path.join(FIG, "fig6_interventions.png"))
    plt.close(fig)
    print("[E6] 完成")


# ================================================================ E7
def e7():
    ps = np.round(np.arange(0, 0.9601, 0.05), 2)
    recs = sweep_p(BUSY, ps)
    df = pd.DataFrame([{k: r[k] for k in
                        ("p", "sf_total_mean", "qf_total_mean", "tray_wait_mean",
                         "sf_seat_wait_mean", "wait_person_min_per_head",
                         "abandon_ratio", "seat_turnover_per_hour")} for r in recs])
    df.to_csv(os.path.join(RES, "e7_endogenous_input.csv"), index=False, encoding="utf-8-sig")

    KAPPA = 1.0     # 端着餐盘找座的额外负效用系数（分钟当量/分钟）
    BETA = 0.6      # 有限理性程度（logit 敏感度, 1/分钟）

    def payoff(p):
        r = df.iloc[(df.p - p).abs().idxmin()]
        u_pre = -r.sf_total_mean
        u_qf = -(r.qf_total_mean + KAPPA * r.tray_wait_mean)
        return u_pre, u_qf

    traj = [0.05]
    for _ in range(60):
        p = traj[-1]
        u_pre, u_qf = payoff(p)
        p_next = 1.0 / (1.0 + np.exp(-BETA * (u_pre - u_qf)))
        traj.append(float(np.clip(p_next, 0, 1)))
        if abs(traj[-1] - p) < 1e-4:
            break
    p_star = traj[-1]

    # 社会福利: 人均总耗时 与 流失率
    def welfare(p):
        r = df.iloc[(df.p - p).abs().idxmin()]
        w = (r.sf_total_mean * min(p, 1) + r.qf_total_mean * (1 - min(p, 1)))
        return float(w), float(r.abandon_ratio), float(r.seat_turnover_per_hour)

    pd.DataFrame(dict(iter=np.arange(len(traj)), p=traj)).to_csv(
        os.path.join(RES, "e7_endogenous_path.csv"), index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.9))
    ax = axes[0]
    ax.plot(df.p, df.sf_total_mean, marker="o", ms=3, color="#c62828",
            label="先占座者的在店总耗时")
    ax.plot(df.p, df.qf_total_mean + KAPPA * df.tray_wait_mean, marker="s", ms=3,
            color="#2e7d32", label="先排队者的在店总耗时 + 端盘等待当量")
    ax.plot(df.p, df.qf_total_mean, ls=":", color="#2e7d32",
            label="先排队者的在店总耗时")
    ax.set_xlabel("先占座学生比例 p")
    ax.set_ylabel("分钟")
    ax.set_title("(a) 个体视角：占座永远“看起来更划算”")
    ax.legend(fontsize=7.5)

    ax = axes[1]
    served_curve = [df.iloc[i]["seat_turnover_per_hour"] for i in range(len(df))]
    turn_curve = np.array(served_curve)
    ab_curve = np.array([welfare(p)[1] * 100 for p in df.p])
    ax.plot(df.p, turn_curve, marker="o", ms=3, color="#37474f", label="座位产出率")
    ax.set_xlabel("先占座学生比例 p")
    ax.set_ylabel("人次/座位/小时", color="#37474f")
    ax.set_title("(b) 社会视角：p 越高，能坐下吃饭的人越少")
    ax2 = ax.twinx()
    ax2.plot(df.p, ab_curve, ls="--", marker="s", ms=3, color="#c62828", label="流失率")
    ax2.set_ylabel("未落座流失率 (%)", color="#c62828")
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7.5)
    p_opt = float(df.p.iloc[int(np.argmax(turn_curve))])
    ax.axvline(p_opt, color="#2e7d32", ls=":", lw=1.5)
    ax.text(p_opt + 0.03, turn_curve.min(), f"社会最优 p≈{p_opt:g}",
            color="#2e7d32", fontsize=8)

    ax = axes[2]
    ax.plot(np.arange(len(traj)), traj, marker="o", ms=3, color="#1565c0")
    ax.axhline(p_star, ls="--", color="#c62828")
    ax.text(2, p_star - 0.09, f"占座均衡 p* = {p_star:.2f}", color="#c62828", fontsize=9)
    ax.set_xlabel("迭代轮次")
    ax.set_ylabel("先占座比例 p")
    ax.set_ylim(0, 1.05)
    ax.set_title("(c) 有限理性复制者动态：收敛到普遍占座")
    fig.suptitle("图7  占座是个体理性、集体受损的“囚徒困境”", fontsize=12.5, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    check_legends(fig, "图7")
    fig.savefig(os.path.join(FIG, "fig7_endogenous.png"))
    plt.close(fig)
    print(f"[E7] 完成, 占座均衡 p* = {p_star:.3f}, 社会最优 p ≈ {p_opt:g}")
    return df, p_star, p_opt


# ================================================================ E8
def e8():
    """行为变体: 硬核占座 / 自适应占座 / 结伴占座。"""
    GRP = ((1, 0.55), (2, 0.25), (3, 0.12), (4, 0.08))
    mean_g = sum(s * p for s, p in GRP)          # 平均同行人数 = 1.73
    # 结伴场景把"批次到达率"按平均人数折算, 保证总就餐人数与其他场景可比
    gl = BUSY.load_scale / mean_g
    variants = [
        ("硬核占座\n(占不到座就干等)", dict(adaptive_seat_first=False)),
        ("自适应占座\n(占不到座就去排队)", dict(adaptive_seat_first=True)),
        ("结伴占座\n(2~4人同行)", dict(adaptive_seat_first=True, group_probs=GRP,
                                    load_scale=gl)),
        ("结伴但允许拆座\n(散客可先坐)", dict(adaptive_seat_first=True, group_probs=GRP,
                                            allow_seat_skip=True, load_scale=gl)),
    ]
    keys = ["seat_effective_util", "seat_turnover_per_hour", "abandon_ratio",
            "seat_wait_mean", "food_wait_mean", "served", "people_served",
            "pre_claimed_share", "total_time_mean", "seat_idle_pre_util"]
    recs = []
    for name, kw in variants:
        for p in (0.0, 0.4, 0.8):
            m = bench(BUSY.copy(p_seat_first=p, **kw), SEEDS)
            recs.append(dict(variant=name.replace("\n", " "), p=p,
                             **{k: m[k] for k in keys},
                             **{k + "_ci": m[k + "_ci"] for k in keys}))
    df = pd.DataFrame(recs)
    df.to_csv(os.path.join(RES, "e8_behavior_variants.csv"), index=False,
              encoding="utf-8-sig")

    fig, axes = plt.subplots(1, 4, figsize=(14, 3.8))
    x = np.arange(len(variants))
    w = 0.26
    ps = (0.0, 0.4, 0.8)
    csl = ["#2e7d32", "#f9a825", "#c62828"]
    for ax, (k, title, sc, yl) in zip(axes, [
            ("seat_effective_util", "(a) 有效座位使用率", 100, "%"),
            ("seat_turnover_per_hour", "(b) 座位产出率", 1, "人次/座位/小时"),
            ("abandon_ratio", "(c) 未落座流失率", 100, "%"),
            ("seat_wait_mean", "(d) 平均找座等待", 1, "分钟")]):
        for i, p in enumerate(ps):
            v = [df[(df.variant == n.replace("\n", " ")) & (df.p == p)][k].iloc[0] * sc
                 for n, _ in variants]
            ci = [df[(df.variant == n.replace("\n", " ")) & (df.p == p)][k + "_ci"].iloc[0] * sc
                  for n, _ in variants]
            ax.bar(x + (i - 1) * w, v, w, yerr=ci, capsize=2, color=csl[i],
                   label=f"占座比例 p={p:g}")
        ax.set_xticks(x)
        ax.set_xticklabels([n for n, _ in variants], fontsize=7.5)
        ax.set_title(title)
        ax.set_ylabel(yl)
        if k == "abandon_ratio":
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda t, _: f"{t:.0f}%"))
    axes[0].legend(fontsize=7.5)
    fig.suptitle("图8  结论对行为假设稳健吗？（繁忙日，24 次重复，误差棒 = 95% CI）",
                 fontsize=12.5, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    check_legends(fig, "图8")
    fig.savefig(os.path.join(FIG, "fig8_behavior_variants.png"))
    plt.close(fig)
    print("[E8] 完成")


# ================================================================ E9
def e9():
    """耐心敏感性: 占座的吞吐损失有多少来自"学生等不下去直接走"? """
    caps = [6.0, 10.0, 15.0, 25.0, 999.0]
    ps = [0.0, 0.2, 0.4, 0.8]
    keys = ["served", "served_rate", "abandon_ratio", "seat_wait_mean",
            "seat_effective_util", "seat_effective_util_w2", "seat_idle_pre_util",
            "seat_turnover_per_hour", "spill_ratio", "food_wait_mean"]
    recs = []
    for cap in caps:
        for p in ps:
            m = bench(BUSY.copy(p_seat_first=p, max_seat_wait_min=cap), SEEDS)
            recs.append(dict(cap=cap, p=p, **{k: m[k] for k in keys},
                             **{k + "_ci": m[k + "_ci"] for k in keys}))
    df = pd.DataFrame(recs)
    df.to_csv(os.path.join(RES, "e9_patience.csv"), index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(1, 4, figsize=(14.5, 3.8))
    lab = {6.0: "6 分钟", 10.0: "10 分钟", 15.0: "15 分钟", 25.0: "25 分钟", 999.0: "无限耐心"}
    xs = np.arange(len(caps))
    csl = ["#2e7d32", "#7cb342", "#f9a825", "#ef6c00", "#c62828"]
    for ax, (k, title, sc, yl) in zip(axes, [
            ("served_rate", "(a) 实际落座就餐率", 100, "%"),
            ("seat_wait_mean", "(b) 平均找座等待", 1, "分钟"),
            ("seat_effective_util", "(c) 有效座位使用率（营业窗口）", 100, "%"),
            ("seat_effective_util_w2", "(d) 有效座位使用率（营业+45分钟）", 100, "%")]):
        for i, p in enumerate(ps):
            v = [df[(df.cap == c) & (df.p == p)][k].iloc[0] * sc for c in caps]
            ax.plot(xs, v, marker="o", ms=4, color=csl[i], label=f"占座比例 p={p:g}")
        ax.set_xticks(xs)
        ax.set_xticklabels([lab[c] for c in caps], fontsize=8)
        ax.set_xlabel("学生耐心上限（等不到座就走）")
        ax.set_title(title)
        ax.set_ylabel(yl)
    axes[0].legend(fontsize=7.5)
    fig.suptitle("图9  耐心敏感性：占座的“吞吐损失”有多少是等不下去走人造成的？",
                 fontsize=12.5, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    check_legends(fig, "图9")
    fig.savefig(os.path.join(FIG, "fig9_patience.png"))
    plt.close(fig)
    print("[E9] 完成")


if __name__ == "__main__":
    which = os.environ.get("EXP", "all")
    if which in ("all", "e1"):
        e1()
    if which in ("all", "e2"):
        e2()
    if which in ("all", "e3"):
        e3()
    if which in ("all", "e45"):
        e4_e5()
    if which in ("all", "e6"):
        e6()
    if which in ("all", "e7"):
        e7()
    if which in ("all", "e8"):
        e8()
    if which in ("all", "e9"):
        e9()
    if which in ("all", "e1"):
        e1()
    if which in ("all", "e2"):
        e2()
    if which in ("all", "e3"):
        e3()
    if which in ("all", "e45"):
        e4_e5()
    if which in ("all", "e6"):
        e6()
    if which in ("all", "e7"):
        e7()
