#!/bin/sh

# pass in the name of the test run as the first argument

run_benchmark() {
  # shellcheck disable=SC2086
  python -m tools.test_full_sync run $3 --profile --test-constants "$1" &
  test_pid=$!
  python -m tools.cpu_utilization $test_pid
  mkdir -p "$2"
  mv test-full-sync.log cpu.png cpu-usage.log plot-cpu.gnuplot "$2"
  python -m tools.test_full_sync analyze
  mv slow-batch-*.profile slow-batch-*.png "$2"
  # python -m chia.util.profiler profile-node >"$2/node-profile.txt"
  # mv profile-node "$2"
}

cd ..

if [ "$1" = "" ]; then
  TEST_NAME="node-benchmark"
else
  TEST_NAME=$1
fi

# generate the test blockchain databases by running:
# python -m tools.generate_chain --fill-rate 0 --length 1500 --block-refs 1
# python -m tools.generate_chain --fill-rate 100 --length 500 --block-refs 0
run_benchmark stress-test-blockchain-1500-0-refs.sqlite "${TEST_NAME}-sync-empty" ""
run_benchmark stress-test-blockchain-1500-0-refs.sqlite "${TEST_NAME}-keepup-empty" --keep-up

run_benchmark stress-test-blockchain-500-100.sqlite "${TEST_NAME}-sync-full" ""
run_benchmark stress-test-blockchain-500-100.sqlite "${TEST_NAME}-keepup-full" --keep-up
