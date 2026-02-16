#!/bin/bash
set -euo pipefail

# ============ Paths ============
GEM5_BIN="/home/g/gbusnot/ES201/tools/TP5/gem5-stable/build/ARM/gem5.fast"
GEM5_CONFIG="/home/g/gbusnot/ES201/tools/TP5/gem5-stable/configs/example/se.py"
APP_BIN="$HOME/TP5/test_omp"

# ============ Fixed matrix size ============
MATRIX_SIZE=128

# ============ Threads to run ============
THREADS_LIST=(1 2 4 8 16)
# ============ Output root ============
OUTPUT_ROOT="${OUTPUT_ROOT:-$HOME/TP5/CORTEXA7/results}"
RUN_ROOT="$OUTPUT_ROOT/m${MATRIX_SIZE}"
mkdir -p "$RUN_ROOT"

# Summary CSV
SUMMARY_CSV="$RUN_ROOT/summary_manualstyle_m${MATRIX_SIZE}.csv"
echo "threads,ipc_max_cpu,cycles_max_cpu,insts_max_cpu,sim_ticks,sim_seconds,run_dir" > "$SUMMARY_CSV"

for t in "${THREADS_LIST[@]}"; do
  RUN_DIR="$RUN_ROOT/t${t}_arm_detailed_L1L2_manualstyle"
  mkdir -p "$RUN_DIR"

  rm -f "$RUN_DIR/stats.txt" "$RUN_DIR/simout" "$RUN_DIR/simerr" \
        "$RUN_DIR/config.ini" "$RUN_DIR/config.json" 2>/dev/null || true

  # Record command
  {
    echo "OMP_NUM_THREADS=$t $GEM5_BIN \\"
    echo "  $GEM5_CONFIG \\"
    echo "  --cpu-type=arm_detailed -n $t \\"
    echo "  -c $APP_BIN -o \"$t $MATRIX_SIZE\" \\"
    echo "  --caches --l2cache"
  } > "$RUN_DIR/cmd.txt"

  echo "=== Running: threads=$t, m=$MATRIX_SIZE -> $RUN_DIR ==="

  # Manual-style run (no --env, no --remote-gdb-port=0)
  OMP_NUM_THREADS="$t" \
  "$GEM5_BIN" -d "$RUN_DIR" \
    "$GEM5_CONFIG" \
    --cpu-type=arm_detailed -n "$t" \
    -c "$APP_BIN" -o "$t $MATRIX_SIZE" \
    --caches --l2cache

  # Extract key metrics
  STATS_FILE="$RUN_DIR/stats.txt"
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

  echo "${t},${ipc_max},${cycles_max},${insts_max},${sim_ticks},${sim_secs},${RUN_DIR}" >> "$SUMMARY_CSV"
done

echo "Done."
echo "All run folders are under: $RUN_ROOT/"
echo "CSV summary is here: $SUMMARY_CSV"
