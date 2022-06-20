#!/bin/sh

run_benchmark() {
   # shellcheck disable=SC2086
   python ./tools/test_full_sync.py run $3 --profile --test-constants "$1" &
   test_pid=$!
   python ./tools/cpu_utilization.py $test_pid
   mkdir -p "$2"
   mv test-full-sync.log cpu.png cpu-usage.log plot-cpu.gnuplot "$2"
   python ./tools/test_full_sync.py analyze
   mv slow-batch-*.profile slow-batch-*.png "$2"
   python ./chia/util/profiler.py profile-node >"$2/node-profile.txt"
   mv profile-node "$2"
}

cd ..

run_benchmark stress-test-blockchain-1500-0-refs.sqlite "$1-sync-empty" ""
run_benchmark stress-test-blockchain-1500-0-refs.sqlite "$1-keepup-empty" --keep-up

run_benchmark stress-test-blockchain-500-100.sqlite "$1-sync-full" ""
run_benchmark stress-test-blockchain-500-100.sqlite "$1-keepup-full" --keep-up
