from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt


DIR_RE = re.compile(r"^t(?P<threads>\d+)(?:_cpus(?P<cpus>\d+))?_")
NUM_CYCLES_RE = re.compile(r"^system\.cpu[0-9]*\.numCycles\s+(\d+)\b")


@dataclass
class Point:
    threads: int
    cycles: int
    folder: str
    speedup: float = 0.0
    efficiency: float = 0.0
    local_speedup: float | None = None
    local_efficiency: float | None = None
    marginal_efficiency: float | None = None


def parse_cycles(stats_path: Path) -> int:
    cycles: list[int] = []
    with stats_path.open("r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            match = NUM_CYCLES_RE.match(line.strip())
            if match:
                cycles.append(int(match.group(1)))

    if not cycles:
        raise ValueError(f"Aucune ligne numCycles trouvee dans {stats_path}")
    return max(cycles)


def collect_points(input_root: Path) -> tuple[list[Point], list[str]]:
    points: list[Point] = []
    warnings: list[str] = []

    if not input_root.exists():
        raise FileNotFoundError(f"Dossier introuvable: {input_root}")

    for entry in sorted(input_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue

        match = DIR_RE.match(entry.name)
        if not match:
            continue

        threads = int(match.group("cpus") or match.group("threads"))
        stats_path = entry / "stats.txt"

        if not stats_path.exists():
            warnings.append(f"{entry.name}: stats.txt absent")
            continue
        if stats_path.stat().st_size == 0:
            warnings.append(f"{entry.name}: stats.txt vide")
            continue

        try:
            cycles = parse_cycles(stats_path)
            points.append(Point(threads=threads, cycles=cycles, folder=entry.name))
        except ValueError as exc:
            warnings.append(str(exc))

    points.sort(key=lambda p: p.threads)
    return points, warnings


def compute_metrics(points: list[Point]) -> list[Point]:
    baseline = next((p for p in points if p.threads == 1), points[0])
    baseline_cycles = baseline.cycles

    for i, point in enumerate(points):
        point.speedup = baseline_cycles / point.cycles
        point.efficiency = point.speedup / point.threads

        if i == 0:
            continue

        prev = points[i - 1]
        d_threads = point.threads - prev.threads

        point.local_speedup = prev.cycles / point.cycles
        point.local_efficiency = point.local_speedup / (point.threads / prev.threads)
        point.marginal_efficiency = (point.speedup - prev.speedup) / d_threads

    return points


def infer_matrix_label(input_root: Path, matrix_label: str | None) -> str:
    if matrix_label:
        return matrix_label

    match = re.fullmatch(r"m(\d+)", input_root.name, re.IGNORECASE)
    if match:
        return f"m={match.group(1)}"
    return input_root.name


def write_csv(points: list[Point], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "threads",
                "cycles_max",
                "speedup_vs_1",
                "efficacite_globale",
                "gain_local",
                "efficacite_locale",
                "efficacite_marginale",
                "folder",
            ]
        )
        for p in points:
            writer.writerow(
                [
                    p.threads,
                    p.cycles,
                    f"{p.speedup:.6f}",
                    f"{p.efficiency:.6f}",
                    "" if p.local_speedup is None else f"{p.local_speedup:.6f}",
                    "" if p.local_efficiency is None else f"{p.local_efficiency:.6f}",
                    "" if p.marginal_efficiency is None else f"{p.marginal_efficiency:.6f}",
                    p.folder,
                ]
            )


def write_report(points: list[Point], report_path: Path, input_root: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as file:
        file.write("Rapport speedup et efficacite (Cortex-A7)\n")
        file.write(f"Source: {input_root}\n\n")
        file.write(
            "Colonnes: threads, cycles_max, speedup_vs_1, efficacite_globale(%), "
            "gain_local, efficacite_locale(%), efficacite_marginale_par_thread(%)\n\n"
        )

        for p in points:
            eff_global = 100.0 * p.efficiency
            local_speed = "-" if p.local_speedup is None else f"{p.local_speedup:.3f}"
            local_eff = "-" if p.local_efficiency is None else f"{100.0 * p.local_efficiency:.1f}"
            marginal = "-" if p.marginal_efficiency is None else f"{100.0 * p.marginal_efficiency:.1f}"

            file.write(
                f"t={p.threads:>2} | cycles={p.cycles:>8} | "
                f"S={p.speedup:>5.3f} | Eglob={eff_global:>6.2f}% | "
                f"GainLocal={local_speed:>5} | Elocale={local_eff:>6}% | "
                f"Emarg={marginal:>6}%\n"
            )

        best = max(points, key=lambda x: x.speedup)
        file.write("\n")
        file.write(
            f"Meilleur speedup observe: S={best.speedup:.3f} pour {best.threads} threads.\n"
        )

        degradations = [p for p in points[1:] if p.local_efficiency is not None and p.local_efficiency < 0.8]
        if degradations:
            file.write("Rendements marginaux en baisse (efficacite locale < 80%):\n")
            for p in degradations:
                file.write(
                    f"- Passage vers {p.threads} threads: "
                    f"{100.0 * p.local_efficiency:.1f}% d'efficacite locale.\n"
                )
        else:
            file.write("Aucune baisse forte d'efficacite locale (<80%) sur les points disponibles.\n")


def plot_speedup(points: list[Point], output_png: Path, matrix_label: str) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)

    x = [p.threads for p in points]
    speedup = [p.speedup for p in points]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot(x, speedup, marker="o", linewidth=2.2, color="#0b66c3", label="Speedup observe")

    ax.set_title(f"Cortex-A7 ({matrix_label}) : Speedup par rapport a 1 thread")
    ax.set_xlabel("Nombre de threads")
    ax.set_ylabel("Speedup S(p) = T1 / Tp")
    ax.set_xticks(x)
    ax.grid(True, linestyle="--", alpha=0.35)
    y_min = min(speedup)
    y_max = max(speedup)
    span = max(y_max - y_min, 0.05)
    ax.set_ylim(max(0.0, y_min - 0.30 * span), y_max + 0.50 * span)

    for thread, s in zip(x, speedup):
        ax.annotate(
            f"{s:.2f}",
            (thread, s),
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

    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def plot_efficiency(points: list[Point], output_png: Path, matrix_label: str) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)

    x = [p.threads for p in points]
    efficiency_pct = [100.0 * p.efficiency for p in points]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot(x, efficiency_pct, marker="s", linewidth=2.0, color="#de6f0d", label="Efficacite globale")
    ax.set_title(f"Cortex-A7 ({matrix_label}) : Efficacite globale")
    ax.set_xlabel("Nombre de threads")
    ax.set_ylabel("Efficacite E(p) = S(p)/p (%)")
    ax.set_xticks(x)
    ax.set_ylim(0, 105)
    ax.grid(True, linestyle="--", alpha=0.35)

    for thread, e in zip(x, efficiency_pct):
        ax.annotate(
            f"{e:.1f}%",
            (thread, e),
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

    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_png, dpi=300)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    default_input = here / "m16"
    parser = argparse.ArgumentParser(
        description="Calcule le speedup (base 1 thread) et genere graphe+rapport."
    )
    parser.add_argument("--input-root", type=Path, default=default_input)
    parser.add_argument(
        "--matrix-label",
        type=str,
        default=None,
        help="Etiquette a afficher dans le titre (ex: m=128). Defaut: detecte depuis --input-root.",
    )
    parser.add_argument(
        "--output-speedup-png",
        type=Path,
        default=here / "speedup_m16_vs_1thread.png",
    )
    parser.add_argument(
        "--output-efficiency-png",
        type=Path,
        default=here / "efficacite_m16.png",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=here / "rapport_efficacite_m16.txt",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=here / "speedup_m16_summary.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        points, warnings = collect_points(args.input_root)
    except FileNotFoundError as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 1

    if not points:
        print("Erreur: aucune configuration exploitable trouvee.", file=sys.stderr)
        for warning in warnings:
            print(f"Avertissement: {warning}", file=sys.stderr)
        return 1

    points = compute_metrics(points)
    matrix_label = infer_matrix_label(args.input_root, args.matrix_label)
    plot_speedup(points, args.output_speedup_png, matrix_label)
    plot_efficiency(points, args.output_efficiency_png, matrix_label)
    write_csv(points, args.output_csv)
    write_report(points, args.output_report, args.input_root)

    for warning in warnings:
        print(f"Avertissement: {warning}")

    print(f"Graphe speedup: {args.output_speedup_png}")
    print(f"Graphe efficacite: {args.output_efficiency_png}")
    print(f"Rapport texte: {args.output_report}")
    print(f"CSV resume: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
