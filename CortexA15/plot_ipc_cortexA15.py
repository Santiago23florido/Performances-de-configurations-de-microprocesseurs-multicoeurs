#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt


DIR_RE = re.compile(r"^w(?P<width>\d+)_t(?P<threads>\d+)$")
CYC_RE = re.compile(r"^system\.cpu\d*\.numCycles\s+(?P<value>\d+)\b")
IPC_RE = re.compile(r"^system\.cpu\d*\.ipc\s+(?P<value>\d+(?:\.\d+)?)\b")
SIM_INS_RE = re.compile(r"^sim_insts\s+(?P<value>\d+)\b")


@dataclass
class Point:
    simulation: str
    width: int
    threads: int
    ipc_max: float
    ipc_global: float
    sim_insts: int
    max_cycles: int
    folder: str


def parse_stats(stats_path: Path) -> tuple[float, float, int, int]:
    cycles: list[int] = []
    ipc_vals: list[float] = []
    sim_insts = 0

    with stats_path.open("r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            text = line.strip()
            m = CYC_RE.match(text)
            if m:
                cycles.append(int(m.group("value")))
                continue
            m = IPC_RE.match(text)
            if m:
                ipc_vals.append(float(m.group("value")))
                continue
            m = SIM_INS_RE.match(text)
            if m:
                sim_insts = int(m.group("value"))

    if not cycles:
        raise ValueError(f"Aucune ligne numCycles dans {stats_path}")
    if not ipc_vals:
        raise ValueError(f"Aucune ligne IPC dans {stats_path}")
    if sim_insts <= 0:
        raise ValueError(f"Aucune valeur sim_insts valide dans {stats_path}")

    max_cycles = max(cycles)
    if max_cycles <= 0:
        raise ValueError(f"Aucun cycle valide dans {stats_path}")

    ipc_max = max(ipc_vals)
    ipc_global = sim_insts / max_cycles
    return ipc_max, ipc_global, sim_insts, max_cycles


def collect(root: Path, simulation: str, max_threads: int | None) -> tuple[list[Point], list[str]]:
    points: list[Point] = []
    warnings: list[str] = []

    if not root.exists():
        warnings.append(f"{root}: dossier absent")
        return points, warnings

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue

        m = DIR_RE.match(entry.name)
        if not m:
            continue

        width = int(m.group("width"))
        threads = int(m.group("threads"))
        if max_threads is not None and threads > max_threads:
            continue

        status_path = entry / "STATUS.txt"
        if status_path.exists():
            status = status_path.read_text(encoding="utf-8", errors="ignore").strip()
            if not status.startswith("OK"):
                warnings.append(f"{simulation}/{entry.name}: ignore ({status})")
                continue

        stats_path = entry / "stats.txt"
        if not stats_path.exists():
            warnings.append(f"{simulation}/{entry.name}: stats.txt absent")
            continue
        if stats_path.stat().st_size == 0:
            warnings.append(f"{simulation}/{entry.name}: stats.txt vide")
            continue

        try:
            ipc_max, ipc_global, sim_insts, max_cycles = parse_stats(stats_path)
            points.append(
                Point(
                    simulation=simulation,
                    width=width,
                    threads=threads,
                    ipc_max=ipc_max,
                    ipc_global=ipc_global,
                    sim_insts=sim_insts,
                    max_cycles=max_cycles,
                    folder=entry.name,
                )
            )
        except ValueError as exc:
            warnings.append(f"{simulation}/{entry.name}: {exc}")

    points.sort(key=lambda p: (p.width, p.threads))
    return points, warnings


def group_by_width(points: list[Point]) -> dict[int, list[Point]]:
    grouped: dict[int, list[Point]] = {}
    for point in points:
        grouped.setdefault(point.width, []).append(point)
    for width in grouped:
        grouped[width].sort(key=lambda p: p.threads)
    return grouped


def write_csv(points_m16: list[Point], points_m128: list[Point], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "simulation",
                "width",
                "threads",
                "ipc_max",
                "ipc_global",
                "sim_insts",
                "max_numCycles",
                "folder",
            ]
        )
        for point in points_m16 + points_m128:
            writer.writerow(
                [
                    point.simulation,
                    point.width,
                    point.threads,
                    f"{point.ipc_max:.6f}",
                    f"{point.ipc_global:.6f}",
                    point.sim_insts,
                    point.max_cycles,
                    point.folder,
                ]
            )


def _annotate(ax: plt.Axes, x: int, y: float, text: str) -> None:
    ax.annotate(
        text,
        (x, y),
        textcoords="offset points",
        xytext=(0, 8),
        ha="center",
        fontsize=8,
        bbox={
            "boxstyle": "round,pad=0.2",
            "facecolor": "white",
            "edgecolor": "#888888",
            "alpha": 0.9,
            "linewidth": 0.6,
        },
    )


def plot_metric(
    grouped_m16: dict[int, list[Point]],
    grouped_m128: dict[int, list[Point]],
    metric: str,
    title: str,
    ylabel: str,
    output_png: Path,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4), sharey=False)
    color_map = plt.get_cmap("tab10")
    widths_all = sorted(set(grouped_m16.keys()) | set(grouped_m128.keys()))
    color_for = {width: color_map(i % 10) for i, width in enumerate(widths_all)}

    for ax, grouped, label in [
        (axes[0], grouped_m16, "m=16"),
        (axes[1], grouped_m128, "m=128"),
    ]:
        xticks_set: set[int] = set()
        for width in sorted(grouped.keys()):
            points = grouped[width]
            x = [p.threads for p in points]
            y = [getattr(p, metric) for p in points]
            xticks_set.update(x)
            ax.plot(x, y, marker="o", linewidth=2.0, color=color_for[width], label=f"Width={width}")
            for xx, yy in zip(x, y):
                _annotate(ax, xx, yy, f"{yy:.3f}")

        if xticks_set:
            ax.set_xticks(sorted(xticks_set))
        ax.set_xlabel("Nombre de threads")
        ax.set_title(label)
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.legend(loc="best")

    axes[0].set_ylabel(ylabel)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--m16-root", type=Path, default=here / "m16")
    parser.add_argument("--m128-root", type=Path, default=here / "m128")
    parser.add_argument("--max-threads", type=int, default=16)
    parser.add_argument(
        "--output-ipc-max-png",
        type=Path,
        default=here / "ipc_max_m16_m128_cortexA15_widths.png",
    )
    parser.add_argument(
        "--output-ipc-global-png",
        type=Path,
        default=here / "ipc_global_m16_m128_cortexA15_widths.png",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=here / "ipc_m16_m128_cortexA15_widths_summary.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    points_m16, warnings_m16 = collect(args.m16_root, "m16", args.max_threads)
    points_m128, warnings_m128 = collect(args.m128_root, "m128", args.max_threads)
    warnings = warnings_m16 + warnings_m128

    if not points_m16 and not points_m128:
        print("Erreur: aucune donnee exploitable.", file=sys.stderr)
        for warning in warnings:
            print(f"Avertissement: {warning}", file=sys.stderr)
        return 1

    grouped_m16 = group_by_width(points_m16)
    grouped_m128 = group_by_width(points_m128)

    plot_metric(
        grouped_m16,
        grouped_m128,
        metric="ipc_max",
        title="IPC maximal par configuration (Cortex-A15, m=16 et m=128)",
        ylabel="IPC maximal (max system.cpu*.ipc)",
        output_png=args.output_ipc_max_png,
    )

    plot_metric(
        grouped_m16,
        grouped_m128,
        metric="ipc_global",
        title="IPC global par configuration (Cortex-A15, m=16 et m=128)",
        ylabel="IPC global = sim_insts / max(numCycles)",
        output_png=args.output_ipc_global_png,
    )

    write_csv(points_m16, points_m128, args.output_csv)

    for warning in warnings:
        print(f"Avertissement: {warning}")

    print(f"Graphe IPC maximal: {args.output_ipc_max_png}")
    print(f"Graphe IPC global: {args.output_ipc_global_png}")
    print(f"CSV resume: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
