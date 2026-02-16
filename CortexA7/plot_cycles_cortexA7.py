from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt


# Accept both historical folders (tX_cpusY_*) and current runs (tX_*).
DIR_RE = re.compile(r"^t(?P<threads>\d+)(?:_cpus(?P<cpus>\d+))?(?:_|$)")
NUM_CYCLES_RE = re.compile(r"^system\.cpu\d*\.numCycles\s+(\d+)\b")
SIM_TICKS_RE = re.compile(r"^sim_ticks\s+(\d+)\b")
CPU_CLOCK_RE = re.compile(r"^system\.cpu_clk_domain\.clock\s+(\d+)\b")
SYS_CLOCK_RE = re.compile(r"^system\.clk_domain\.clock\s+(\d+)\b")


def parse_cycles(stats_path: Path) -> tuple[int, str]:
    cpu_cycles: list[int] = []
    sim_ticks: int | None = None
    cpu_clock: int | None = None
    sys_clock: int | None = None

    with stats_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            match = NUM_CYCLES_RE.match(line)
            if match:
                cpu_cycles.append(int(match.group(1)))
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

    if cpu_cycles:
        return max(cpu_cycles), "max(system.cpu*.numCycles)"

    if sim_ticks is not None:
        clock_period = cpu_clock if cpu_clock is not None else sys_clock
        if clock_period and clock_period > 0:
            cycles = int(round(sim_ticks / clock_period))
            return cycles, "sim_ticks / clock_period"

    raise ValueError("Impossible d'extraire les cycles depuis stats.txt")


def collect_data(input_root: Path) -> tuple[list[tuple[int, int, str]], list[str]]:
    points: list[tuple[int, int, str]] = []
    warnings: list[str] = []

    if not input_root.exists():
        raise FileNotFoundError(f"Dossier introuvable: {input_root}")

    for entry in sorted(input_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue

        dir_match = DIR_RE.match(entry.name)
        if not dir_match:
            continue

        cpus_group = dir_match.group("cpus")
        cpus = int(cpus_group) if cpus_group is not None else int(dir_match.group("threads"))
        stats_path = entry / "stats.txt"

        if not stats_path.exists():
            warnings.append(f"{entry.name}: stats.txt absent")
            continue
        if stats_path.stat().st_size == 0:
            warnings.append(f"{entry.name}: stats.txt vide")
            continue

        try:
            cycles, source = parse_cycles(stats_path)
            points.append((cpus, cycles, entry.name))
            print(f"{entry.name}: {cycles} cycles ({source})")
        except ValueError as exc:
            warnings.append(f"{entry.name}: {exc}")

    points.sort(key=lambda row: row[0])
    return points, warnings


def make_plot(points: list[tuple[int, int, str]], output_png: Path) -> None:
    x_values = [p[0] for p in points]
    y_values = [p[1] for p in points]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(x_values, y_values, marker="o", linewidth=2, color="#1f77b4")
    ax.set_title("Cortex-A7 : cycles d'execution selon le nombre de processus")
    ax.set_xlabel("Nombre de processus executes")
    ax.set_ylabel("Nombre de cycles d'execution")
    ax.set_xticks(x_values)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.margins(x=0.05)

    y_min = min(y_values)
    y_max = max(y_values)
    span = max(y_max - y_min, 1)
    y_pad_bottom = 0.08 * span
    y_pad_top = 0.14 * span
    y_lower = max(0, y_min - y_pad_bottom)
    y_upper = y_max + y_pad_top
    ax.set_ylim(y_lower, y_upper)

    for x_val, y_val in zip(x_values, y_values):
        near_top = y_val > (y_max - 0.15 * span)
        y_offset = -12 if near_top else 8
        va = "top" if near_top else "bottom"
        ax.annotate(
            f"{y_val:,}".replace(",", " "),
            (x_val, y_val),
            textcoords="offset points",
            xytext=(0, y_offset),
            ha="center",
            va=va,
            fontsize=8,
            zorder=4,
            clip_on=True,
            bbox={
                "boxstyle": "round,pad=0.2",
                "facecolor": "white",
                "edgecolor": "#808080",
                "alpha": 0.9,
                "linewidth": 0.6,
            },
        )

    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    default_input = script_dir / "m16"
    default_output = script_dir / "cycles_execution_cortexA7.png"

    parser = argparse.ArgumentParser(
        description=(
            "Extrait les cycles d'execution des dossiers CortexA7 "
            "et genere un graphique PNG."
        )
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=default_input,
        help=f"Dossier contenant les configurations (defaut: {default_input})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"Fichier PNG de sortie (defaut: {default_output})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        points, warnings = collect_data(args.input_root)
    except FileNotFoundError as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 1

    if not points:
        print("Erreur: aucune configuration exploitable n'a ete trouvee.", file=sys.stderr)
        for warning in warnings:
            print(f"Avertissement: {warning}", file=sys.stderr)
        return 1

    output_png = args.output
    output_png.parent.mkdir(parents=True, exist_ok=True)
    make_plot(points, output_png)

    for warning in warnings:
        print(f"Avertissement: {warning}")

    print(f"Graphique exporte: {output_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
