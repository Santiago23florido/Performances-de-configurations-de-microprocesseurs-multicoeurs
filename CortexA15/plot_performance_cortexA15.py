from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt


DIR_PATTERNS = [
    re.compile(r"^w(?P<width>\d+)_t(?P<threads>\d+)$"),
    re.compile(r"^t(?P<threads>\d+)_w(?P<width>\d+)(?:_|$)"),
]
NUM_CYCLES_RE = re.compile(r"^system\.cpu(?:\d+)?\.numCycles\s+(\d+)\b")
SIM_TICKS_RE = re.compile(r"^sim_ticks\s+(\d+)\b")
CPU_CLOCK_RE = re.compile(r"^system\.cpu_clk_domain\.clock\s+(\d+)\b")
SYS_CLOCK_RE = re.compile(r"^system\.clk_domain\.clock\s+(\d+)\b")


@dataclass
class Point:
    width: int
    threads: int
    cycles: int
    folder: str
    speedup: float = 0.0
    efficiency: float = 0.0


def parse_dir_name(name: str) -> tuple[int, int] | None:
    for pattern in DIR_PATTERNS:
        match = pattern.match(name)
        if match:
            return int(match.group("width")), int(match.group("threads"))
    return None


def parse_cycles(stats_path: Path) -> int:
    cycles: list[int] = []
    sim_ticks: int | None = None
    cpu_clock: int | None = None
    sys_clock: int | None = None

    with stats_path.open("r", encoding="utf-8", errors="ignore") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line:
                continue

            match = NUM_CYCLES_RE.match(line)
            if match:
                cycles.append(int(match.group(1)))
                continue

            if sim_ticks is None:
                match = SIM_TICKS_RE.match(line)
                if match:
                    sim_ticks = int(match.group(1))
                    continue

            if cpu_clock is None:
                match = CPU_CLOCK_RE.match(line)
                if match:
                    cpu_clock = int(match.group(1))
                    continue

            if sys_clock is None:
                match = SYS_CLOCK_RE.match(line)
                if match:
                    sys_clock = int(match.group(1))

    if cycles:
        return max(cycles)

    if sim_ticks is not None:
        period = cpu_clock if cpu_clock is not None else sys_clock
        if period and period > 0:
            return int(round(sim_ticks / period))

    raise ValueError(f"Impossible d'extraire les cycles depuis {stats_path}")


def collect_points(input_root: Path, max_threads: int | None = None) -> tuple[list[Point], list[str]]:
    if not input_root.exists():
        raise FileNotFoundError(f"Dossier introuvable: {input_root}")

    points: list[Point] = []
    warnings: list[str] = []

    for entry in sorted(input_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue

        parsed = parse_dir_name(entry.name)
        if parsed is None:
            continue
        width, threads = parsed
        if max_threads is not None and threads > max_threads:
            continue

        status_path = entry / "STATUS.txt"
        if status_path.exists():
            status = status_path.read_text(encoding="utf-8", errors="ignore").strip()
            if not status.startswith("OK"):
                warnings.append(f"{entry.name}: ignore ({status})")
                continue

        stats_path = entry / "stats.txt"
        if not stats_path.exists():
            warnings.append(f"{entry.name}: stats.txt absent")
            continue
        if stats_path.stat().st_size == 0:
            warnings.append(f"{entry.name}: stats.txt vide")
            continue

        try:
            cycles = parse_cycles(stats_path)
            points.append(Point(width=width, threads=threads, cycles=cycles, folder=entry.name))
        except ValueError as exc:
            warnings.append(str(exc))

    points.sort(key=lambda p: (p.width, p.threads))
    return points, warnings


def compute_metrics(points: list[Point]) -> dict[int, list[Point]]:
    grouped: dict[int, list[Point]] = {}
    for point in points:
        grouped.setdefault(point.width, []).append(point)

    for width, values in grouped.items():
        values.sort(key=lambda p: p.threads)
        baseline = next((p for p in values if p.threads == 1), values[0])
        baseline_cycles = baseline.cycles
        for point in values:
            point.speedup = baseline_cycles / point.cycles
            point.efficiency = point.speedup / point.threads
    return grouped


def infer_matrix_label(input_root: Path, explicit_label: str | None) -> str:
    if explicit_label:
        return explicit_label
    match = re.fullmatch(r"m(\d+)", input_root.name, re.IGNORECASE)
    if match:
        return f"m={match.group(1)}"
    return input_root.name


def annotate(ax: plt.Axes, x: int, y: float, text: str) -> None:
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
            "edgecolor": "#808080",
            "alpha": 0.9,
            "linewidth": 0.6,
        },
    )


def plot_cycles(grouped: dict[int, list[Point]], output_png: Path, matrix_label: str) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    color_map = plt.get_cmap("tab10")
    widths = sorted(grouped.keys())

    x_all: set[int] = set()
    for idx, width in enumerate(widths):
        values = grouped[width]
        x = [p.threads for p in values]
        y = [p.cycles for p in values]
        x_all.update(x)
        color = color_map(idx % 10)
        ax.plot(x, y, marker="o", linewidth=2.2, color=color, label=f"Width={width}")
        for p in values:
            annotate(ax, p.threads, p.cycles, f"{p.cycles:,}".replace(",", " "))

    ax.set_title(f"Cortex-A15 ({matrix_label}) : cycles d'execution selon le nombre de threads")
    ax.set_xlabel("Nombre de threads")
    ax.set_ylabel("Nombre de cycles d'execution")
    ax.set_xticks(sorted(x_all))
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def plot_res_ejec_cycles(grouped: dict[int, list[Point]], output_png: Path, matrix_label: str) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    color_map = plt.get_cmap("tab10")
    widths = sorted(grouped.keys())

    x_all: set[int] = set()
    cycles_by_width: dict[int, dict[int, int]] = {}
    for width in widths:
        rows: dict[int, int] = {}
        for point in grouped[width]:
            x_all.add(point.threads)
            rows[point.threads] = point.cycles
        cycles_by_width[width] = rows

    x_ticks = sorted(x_all)
    x_base = list(range(len(x_ticks)))
    n = len(widths)
    bar_w = min(0.8 / max(n, 1), 0.28)

    for idx, width in enumerate(widths):
        offset = (idx - (n - 1) / 2.0) * bar_w
        x_pos = [x + offset for x in x_base]
        y_vals = [cycles_by_width[width].get(thread, 0) for thread in x_ticks]
        color = color_map(idx % 10)
        bars = ax.bar(x_pos, y_vals, width=bar_w * 0.95, color=color, label=f"Width={width}", alpha=0.9)
        for bar, y in zip(bars, y_vals):
            if y <= 0:
                continue
            ax.annotate(
                f"{y:,}".replace(",", " "),
                (bar.get_x() + bar.get_width() / 2.0, y),
                textcoords="offset points",
                xytext=(0, 4),
                ha="center",
                fontsize=7,
                bbox={
                    "boxstyle": "round,pad=0.2",
                    "facecolor": "white",
                    "edgecolor": "#808080",
                    "alpha": 0.9,
                    "linewidth": 0.6,
                },
            )

    ax.set_title(f"Cortex-A15 ({matrix_label}) : resultats d'execution (nombre de cycles)")
    ax.set_xlabel("Nombre de threads")
    ax.set_ylabel("Nombre de cycles d'execution")
    ax.set_xticks(x_base)
    ax.set_xticklabels([str(thread) for thread in x_ticks])
    ax.grid(True, linestyle="--", alpha=0.35, axis="y")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def plot_speedup(grouped: dict[int, list[Point]], output_png: Path, matrix_label: str) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    color_map = plt.get_cmap("tab10")
    widths = sorted(grouped.keys())

    x_all: set[int] = set()
    for width in widths:
        for point in grouped[width]:
            x_all.add(point.threads)
    x_ticks = sorted(x_all)
    x_pos = {thread: idx for idx, thread in enumerate(x_ticks)}

    observed_speedups: list[float] = []
    for idx, width in enumerate(widths):
        values = grouped[width]
        x = [x_pos[p.threads] for p in values]
        y = [p.speedup for p in values]
        observed_speedups.extend(y)
        color = color_map(idx % 10)
        ax.plot(x, y, marker="o", linewidth=2.2, color=color, label=f"Width={width}")
        for p in values:
            annotate(ax, x_pos[p.threads], p.speedup, f"{p.speedup:.2f}")

    if observed_speedups:
        y_min = min(observed_speedups)
        y_max = max(observed_speedups)
        y_span = max(y_max - y_min, 0.05)
        ax.set_ylim(max(0.0, y_min - 0.25 * y_span), y_max + 0.45 * y_span)

    ax.set_title(f"Cortex-A15 ({matrix_label}) : speedup par rapport a 1 thread")
    ax.set_xlabel("Nombre de threads")
    ax.set_ylabel("Speedup S(p) = T1 / Tp")
    ax.set_xticks(list(range(len(x_ticks))))
    ax.set_xticklabels([str(thread) for thread in x_ticks])
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="upper left")

    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def plot_efficiency(grouped: dict[int, list[Point]], output_png: Path, matrix_label: str) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    color_map = plt.get_cmap("tab10")
    widths = sorted(grouped.keys())

    x_all: set[int] = set()
    for idx, width in enumerate(widths):
        values = grouped[width]
        x = [p.threads for p in values]
        y = [100.0 * p.efficiency for p in values]
        x_all.update(x)
        color = color_map(idx % 10)
        ax.plot(x, y, marker="s", linewidth=2.2, color=color, label=f"Width={width}")
        for p in values:
            annotate(ax, p.threads, 100.0 * p.efficiency, f"{100.0 * p.efficiency:.1f}%")

    ax.axhline(100.0, linestyle="--", linewidth=1.8, color="#666666", label="Efficacite ideale (100%)")
    ax.set_title(f"Cortex-A15 ({matrix_label}) : efficacite globale")
    ax.set_xlabel("Nombre de threads")
    ax.set_ylabel("Efficacite E(p) = S(p)/p (%)")
    ax.set_xticks(sorted(x_all))
    ax.set_ylim(0, 105)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def write_csv(grouped: dict[int, list[Point]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["width", "threads", "cycles_max", "speedup_vs_1", "efficacite_globale"])
        for width in sorted(grouped.keys()):
            for point in grouped[width]:
                writer.writerow(
                    [
                        width,
                        point.threads,
                        point.cycles,
                        f"{point.speedup:.6f}",
                        f"{point.efficiency:.6f}",
                    ]
                )


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Genere les graphes cycles/speedup/efficacite pour Cortex-A15 avec une courbe par width."
    )
    parser.add_argument("--input-root", type=Path, default=here / "m16")
    parser.add_argument("--matrix-label", type=str, default=None)
    parser.add_argument("--max-threads", type=int, default=None)
    parser.add_argument(
        "--output-cycles-png",
        type=Path,
        default=here / "cycles_execution_m16_cortexA15_widths.png",
    )
    parser.add_argument(
        "--output-res-ejec-png",
        type=Path,
        default=here / "res_ejec_cycles_m16_cortexA15_widths.png",
    )
    parser.add_argument(
        "--output-speedup-png",
        type=Path,
        default=here / "speedup_m16_vs_1thread_cortexA15_widths.png",
    )
    parser.add_argument(
        "--output-efficiency-png",
        type=Path,
        default=here / "efficacite_m16_cortexA15_widths.png",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=here / "speedup_m16_cortexA15_widths_summary.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        points, warnings = collect_points(args.input_root, args.max_threads)
    except FileNotFoundError as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 1

    if not points:
        print("Erreur: aucune configuration exploitable trouvee.", file=sys.stderr)
        for warning in warnings:
            print(f"Avertissement: {warning}", file=sys.stderr)
        return 1

    grouped = compute_metrics(points)
    matrix_label = infer_matrix_label(args.input_root, args.matrix_label)

    plot_cycles(grouped, args.output_cycles_png, matrix_label)
    plot_res_ejec_cycles(grouped, args.output_res_ejec_png, matrix_label)
    plot_speedup(grouped, args.output_speedup_png, matrix_label)
    plot_efficiency(grouped, args.output_efficiency_png, matrix_label)
    write_csv(grouped, args.output_csv)

    for warning in warnings:
        print(f"Avertissement: {warning}")

    print(f"Graphe cycles: {args.output_cycles_png}")
    print(f"Graphe res execution: {args.output_res_ejec_png}")
    print(f"Graphe speedup: {args.output_speedup_png}")
    print(f"Graphe efficacite: {args.output_efficiency_png}")
    print(f"CSV resume: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
