#!/bin/bash
set -euo pipefail

# ===================== USER SETTINGS (edit if needed) =====================
GEM5_BIN="/home/g/gbusnot/ES201/tools/TP5/gem5-stable/build/ARM/gem5.fast"
GEM5_CONFIG="/home/g/gbusnot/ES201/tools/TP5/gem5-stable/configs/example/se.py"
APP_BIN="$HOME/TP5/test_omp"

MATRIX_SIZE=128                  # Fixed matrix size (m)
OUTPUT_ROOT="$HOME/TP5/CORTEXA7/results"   # All run folders will be created here
CPU_MODEL="arm_detailed"

# Enable L1 caches + unified L2 cache
CACHE_ARGS="--caches --l2cache"

# IMPORTANT: disable remote GDB sockets (prevents "Too many open files" on many CPUs)
GEM5_EXTRA_ARGS="--remote-gdb-port=0"

# Thread values: 1,2,4,8,16,...,m  (default follows the statement)
# You can cap it without editing the script by running:  MAX_THREADS=16 ./run_all_cmp.sh
MAX_THREADS="${MAX_THREADS:-$MATRIX_SIZE}"
# ==========================================================================

# --------------------- Sanity checks ---------------------
[ -x "$GEM5_BIN" ]    || { echo "ERROR: GEM5 binary not executable: $GEM5_BIN"; exit 1; }
[ -f "$GEM5_CONFIG" ] || { echo "ERROR: GEM5 config not found: $GEM5_CONFIG"; exit 1; }
[ -x "$APP_BIN" ]     || { echo "ERROR: App binary not executable: $APP_BIN"; exit 1; }

mkdir -p "$OUTPUT_ROOT"

# Build thread list: 1,2,4,... up to MAX_THREADS, and also include MATRIX_SIZE if needed.
THREAD_LIST=()
t=1
while [ "$t" -lt "$MAX_THREADS" ]; do
  THREAD_LIST+=("$t")
  t=$((t * 2))
done
THREAD_LIST+=("$MAX_THREADS")

# If the statement requires going up to m, ensure MATRIX_SIZE is included as last point.
if [ "$MAX_THREADS" -lt "$MATRIX_SIZE" ]; then
  THREAD_LIST+=("$MATRIX_SIZE")
fi

# Optional CSV summary (kept inside CORTEXA7/results as well)
SUMMARY_CSV="$OUTPUT_ROOT/summary_m${MATRIX_SIZE}.csv"
echo "threads,ipc_max_cpu,cycles_max_cpu,insts_max_cpu,sim_ticks,sim_seconds" > "$SUMMARY_CSV"

for threads in "${THREAD_LIST[@]}"; do
  # One folder per run, clearly identified, stored INSIDE CORTEXA7
  RUN_DIR="$OUTPUT_ROOT/m${MATRIX_SIZE}/t${threads}_cpus${threads}_${CPU_MODEL}_L1L2"
  mkdir -p "$RUN_DIR"

  # Environment file read by se.py (sets OMP_NUM_THREADS for the workload)
  ENV_FILE="$RUN_DIR/env"
  echo "OMP_NUM_THREADS=$threads" > "$ENV_FILE"

  # Record the exact command line used (for reproducibility)
  CMD_FILE="$RUN_DIR/cmd.txt"
  echo "$GEM5_BIN $GEM5_EXTRA_ARGS -d $RUN_DIR $GEM5_CONFIG --cpu-type=$CPU_MODEL -n $threads $CACHE_ARGS --cmd=$APP_BIN --options=\"$threads $MATRIX_SIZE\" --env $ENV_FILE" > "$CMD_FILE"

  # Small run info file
  INFO_FILE="$RUN_DIR/run_info.txt"
  {
    echo "date: $(date)"
    echo "host: $(hostname)"
    echo "matrix_size: $MATRIX_SIZE"
    echo "threads: $threads"
    echo "cpu_model: $CPU_MODEL"
    echo "cache_args: $CACHE_ARGS"
    echo "gem5_bin: $GEM5_BIN"
    echo "gem5_config: $GEM5_CONFIG"
    echo "app_bin: $APP_BIN"
    echo "env_file: $ENV_FILE"
  } > "$INFO_FILE"

  # If re-running, avoid mixing old/new outputs
  rm -f "$RUN_DIR/stats.txt" "$RUN_DIR/simout" "$RUN_DIR/simerr" \
        "$RUN_DIR/config.ini" "$RUN_DIR/config.json" 2>/dev/null || true

  echo "=== Running: threads=$threads, m=$MATRIX_SIZE -> $RUN_DIR ==="

  # Run gem5. All standard gem5 outputs will be created INSIDE RUN_DIR (stats.txt, simout, simerr, config.ini, ...)
  "$GEM5_BIN" $GEM5_EXTRA_ARGS -d "$RUN_DIR" "$GEM5_CONFIG" \
    --cpu-type="$CPU_MODEL" -n "$threads" \
    $CACHE_ARGS \
    --cmd="$APP_BIN" --options="$threads $MATRIX_SIZE" \
    --env "$ENV_FILE"

  # Extract a few key metrics from stats.txt (best-effort; names can vary)
  STATS_FILE="$RUN_DIR/stats.txt"
  if [ -f "$STATS_FILE" ]; then
    # Max cycles among CPUs (application makespan proxy)
    cycles_max=$(grep -E "system\.cpu[0-9]+\.numCycles" "$STATS_FILE" 2>/dev/null | awk '{print $2}' | sort -n | tail -1 || true)

    # Max committed instructions among CPUs (best-effort key name)
    insts_max=$(grep -E "system\.cpu[0-9]+\.(numInsts|committedInsts)" "$STATS_FILE" 2>/dev/null | awk '{print $2}' | sort -n | tail -1 || true)

    # Max IPC among CPUs (if present)
    ipc_max=$(grep -E "system\.cpu[0-9]+\.ipc" "$STATS_FILE" 2>/dev/null | awk '{print $2}' | sort -n | tail -1 || true)

    sim_ticks=$(grep -m1 -E "^sim_ticks" "$STATS_FILE" 2>/dev/null | awk '{print $2}' || true)
    sim_secs=$(grep -m1 -E "^sim_seconds" "$STATS_FILE" 2>/dev/null | awk '{print $2}' || true)

    echo "${threads},${ipc_max:-},${cycles_max:-},${insts_max:-},${sim_ticks:-},${sim_secs:-}" >> "$SUMMARY_CSV"
  fi
done

echo "Done."
echo "All run folders are under: $OUTPUT_ROOT/m${MATRIX_SIZE}/"
echo "CSV summary is here: $SUMMARY_CSV"
