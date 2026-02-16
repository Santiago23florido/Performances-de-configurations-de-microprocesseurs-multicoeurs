#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt


DIR_RE = re.compile(r"^t(?P<threads>\d+)_")
CYC_RE = re.compile(r"^system\.cpu(?P<cpu>\d*)\.numCycles\s+(?P<value>\d+)\b")
SIM_INS_RE = re.compile(r"^sim_insts\s+(?P<value>\d+)\b")


def parse_config(stats_path: Path) -> tuple[float, int, int]:
    cycles: dict[str, int] = {}
    sim_insts = 0

    with stats_path.open("r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            text = line.strip()
            m = CYC_RE.match(text)
            if m:
                cycles[m.group("cpu")] = int(m.group("value"))
                continue
            m = SIM_INS_RE.match(text)
            if m:
                sim_insts = int(m.group("value"))

    if not cycles:
        raise ValueError(f"Aucune ligne numCycles dans {stats_path}")
    if sim_insts <= 0:
        raise ValueError(f"Aucune valeur sim_insts valide dans {stats_path}")

    max_cycles = max(cycles.values())
    if max_cycles <= 0:
        raise ValueError(f"Aucun cycle valide dans {stats_path}")

    ipc_global = sim_insts / max_cycles
    return ipc_global, sim_insts, max_cycles


def collect(root: Path) -> tuple[list[tuple[int, float, int, int]], list[str]]:
    data: list[tuple[int, float, int, int]] = []
    warnings: list[str] = []

    if not root.exists():
        warnings.append(f"{root}: dossier absent")
        return data, warnings

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        m = DIR_RE.match(entry.name)
        if not m:
            continue

        threads = int(m.group("threads"))
        stats = entry / "stats.txt"
        if not stats.exists():
            warnings.append(f"{entry.name}: stats.txt absent")
            continue
        if stats.stat().st_size == 0:
            warnings.append(f"{entry.name}: stats.txt vide")
            continue

        try:
            ipc_global, sim_insts, max_cycles = parse_config(stats)
            data.append((threads, ipc_global, sim_insts, max_cycles))
        except ValueError as exc:
            warnings.append(str(exc))

    data.sort(key=lambda x: x[0])
    return data, warnings


def write_csv(
    m16: list[tuple[int, float, int, int]],
    m128: list[tuple[int, float, int, int]],
    output_csv: Path,
) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["simulation", "threads", "ipc_global", "sim_insts", "max_numCycles"])
        for threads, ipc_global, sim_insts, max_cycles in m16:
            writer.writerow(["m16", threads, f"{ipc_global:.6f}", sim_insts, max_cycles])
        for threads, ipc_global, sim_insts, max_cycles in m128:
            writer.writerow(["m128", threads, f"{ipc_global:.6f}", sim_insts, max_cycles])


def plot(
    m16: list[tuple[int, float, int, int]],
    m128: list[tuple[int, float, int, int]],
    output_png: Path,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)

    x16 = [p[0] for p in m16]
    y16 = [p[1] for p in m16]
    x128 = [p[0] for p in m128]
    y128 = [p[1] for p in m128]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    if x16:
        ax.plot(x16, y16, marker="o", linewidth=2.0, color="#0b66c3", label="m=16")
    if x128:
        ax.plot(x128, y128, marker="s", linewidth=2.0, color="#de6f0d", label="m=128")

    for x, y in zip(x16, y16):
        ax.annotate(
            f"{y:.3f}",
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
    for x, y in zip(x128, y128):
        ax.annotate(
            f"{y:.3f}",
            (x, y),
            textcoords="offset points",
            xytext=(0, -14),
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

    xticks = sorted(set(x16 + x128))
    if xticks:
        ax.set_xticks(xticks)
    ax.set_xlabel("Nombre de threads")
    ax.set_ylabel("IPC global = sim_insts / max(numCycles)")
    ax.set_title("IPC global par configuration (m=16 et m=128)")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--m16-root", type=Path, default=root / "m16")
    parser.add_argument("--m128-root", type=Path, default=root / "m128")
    parser.add_argument(
        "--output-png",
        type=Path,
        default=Path(__file__).resolve().parent / "ipc_global_m16_m128.png",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path(__file__).resolve().parent / "ipc_global_m16_m128.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    m16, w16 = collect(args.m16_root)
    m128, w128 = collect(args.m128_root)

    warnings = w16 + w128
    if not m16 and not m128:
        print("Erreur: aucune donnee exploitable.", file=sys.stderr)
        for w in warnings:
            print(f"Avertissement: {w}", file=sys.stderr)
        return 1

    plot(m16, m128, args.output_png)
    write_csv(m16, m128, args.output_csv)

    for w in warnings:
        print(f"Avertissement: {w}")
    print(f"Graphe: {args.output_png}")
    print(f"CSV: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
