#!/bin/bash
set -u -o pipefail

# ========= Config =========
MATRIX_SIZE=16

# gem5 paths (puedes sobreescribir con variables de entorno si quieres)
GEM5_ROOT="${GEM5_ROOT:-/home/g/gbusnot/ES201/tools/TP5/gem5-stable}"
GEM5_BIN="${GEM5_BIN:-$GEM5_ROOT/build/ARM/gem5.fast}"
GEM5_CONFIG="${GEM5_CONFIG:-$GEM5_ROOT/configs/example/se.py}"
NOFILE_LIMIT="${NOFILE_LIMIT:-4096}"

# Reduce aborts when gem5 opens many FDs (e.g., one remote GDB socket per CPU)
ulimit -n "$NOFILE_LIMIT" 2>/dev/null || true

# App
APP_BIN="${APP_BIN:-$HOME/TP5/test_omp}"

# Output: CORTEXA15
OUTPUT_ROOT="${OUTPUT_ROOT:-$HOME/TP5/CORTEXA15/results}"
RUN_ROOT="$OUTPUT_ROOT/m${MATRIX_SIZE}"
mkdir -p "$RUN_ROOT"

# Widths (voies)
WIDTH_LIST=(2 4 8)

# Threads: 1,2,4,...,m (incluye m)
THREADS_LIST=()
t=1
while [ "$t" -le "$MATRIX_SIZE" ]; do
  THREADS_LIST+=("$t")
  t=$((t * 2))
done
if [ "${THREADS_LIST[-1]}" -ne "$MATRIX_SIZE" ]; then
  THREADS_LIST+=("$MATRIX_SIZE")
fi

# Summary CSV
SUMMARY_CSV="$RUN_ROOT/summary_m${MATRIX_SIZE}_A15_detailed_o3width.csv"
echo "threads,width,ipc_max_cpu,cycles_max_cpu,insts_max_cpu,sim_ticks,sim_seconds,run_dir,status" > "$SUMMARY_CSV"

for W in "${WIDTH_LIST[@]}"; do
  for T in "${THREADS_LIST[@]}"; do
    OUTDIR="$RUN_ROOT/w${W}_t${T}"
    mkdir -p "$OUTDIR"

    # Limpia logs/estado anterior (no borro por defecto todo el outdir)
    rm -f "$OUTDIR/console.out" "$OUTDIR/console.err" "$OUTDIR/STATUS.txt" "$OUTDIR/error.log" "$OUTDIR/cmd.txt" 2>/dev/null || true

    # Guarda comando reproducible
    {
      echo "OMP_NUM_THREADS=$T \\"
      echo "\"$GEM5_BIN\" --remote-gdb-port=0 --outdir=\"$OUTDIR\" \\"
      echo "  \"$GEM5_CONFIG\" \\"
      echo "  --caches --l2cache \\"
      echo "  -n $T --cpu-type=detailed --o3-width=$W \\"
      echo "  -c \"$APP_BIN\" -o \"$T $MATRIX_SIZE\""
    } > "$OUTDIR/cmd.txt"

    echo "=== Run: W=$W, T=$T, m=$MATRIX_SIZE -> $OUTDIR ==="

    # Ejecuta (no cortar si falla)
    OMP_NUM_THREADS="$T" \
    "$GEM5_BIN" --remote-gdb-port=0 --outdir="$OUTDIR" \
      "$GEM5_CONFIG" \
      --caches --l2cache \
      -n "$T" --cpu-type=detailed --o3-width="$W" \
      -c "$APP_BIN" -o "$T $MATRIX_SIZE" \
      >"$OUTDIR/console.out" 2>"$OUTDIR/console.err"

    RC=$?

    if [ "$RC" -ne 0 ]; then
      echo "FAIL rc=$RC" > "$OUTDIR/STATUS.txt"
      {
        echo "gem5 failed with rc=$RC"
        echo "---- console.err ----"
        cat "$OUTDIR/console.err" 2>/dev/null || true
      } > "$OUTDIR/error.log"

      # Deja archivos clave vacíos (0 bytes)
      : > "$OUTDIR/stats.txt"
      : > "$OUTDIR/simout"
      : > "$OUTDIR/simerr"
      : > "$OUTDIR/config.ini"
      : > "$OUTDIR/config.json"

      echo "${T},${W},,,,,,${OUTDIR},FAIL" >> "$SUMMARY_CSV"
      continue
    fi

    echo "OK" > "$OUTDIR/STATUS.txt"

    # Extrae métricas
    STATS_FILE="$OUTDIR/stats.txt"
    ipc_max=""
    cycles_max=""
    insts_max=""
    sim_ticks=""
    sim_secs=""

    if [ -f "$STATS_FILE" ]; then
      cycles_max=$(grep -E "system\.cpu[0-9]+\.numCycles" "$STATS_FILE" 2>/dev/null | awk '{print $2}' | sort -n | tail -1 || true)
      insts_max=$(grep -E "system\.cpu[0-9]+\.(numInsts|committedInsts)" "$STATS_FILE" 2>/dev/null | awk '{print $2}' | sort -n | tail -1 || true)
      ipc_max=$(grep -E "system\.cpu[0-9]+\.ipc" "$STATS_FILE" 2>/dev/null | awk '{print $2}' | sort -n | tail -1 || true)
      sim_ticks=$(grep -m1 -E "^sim_ticks" "$STATS_FILE" 2>/dev/null | awk '{print $2}' || true)
      sim_secs=$(grep -m1 -E "^sim_seconds" "$STATS_FILE" 2>/dev/null | awk '{print $2}' || true)
    fi

    echo "${T},${W},${ipc_max},${cycles_max},${insts_max},${sim_ticks},${sim_secs},${OUTDIR},OK" >> "$SUMMARY_CSV"
  done
done

echo "Done."
echo "Resultados en: $RUN_ROOT"
echo "CSV: $SUMMARY_CSV"
