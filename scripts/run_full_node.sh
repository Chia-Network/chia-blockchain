. .venv/bin/activate
. scripts/common.sh

# Starts a full node
_run_bg_cmd python -m src.server.start_full_node 8444 -id 1 -u 8222

wait
