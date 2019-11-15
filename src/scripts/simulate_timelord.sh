. .venv/bin/activate
. src/scripts/common.sh

# Starts a timelord, and a full node

_run_bg_cmd python -m src.server.start_timelord
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8444 -t -u 8222

wait
