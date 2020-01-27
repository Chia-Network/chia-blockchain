. .venv/bin/activate
. scripts/common.sh

# Starts a full node
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8444 -id 3
# _run_bg_cmd python -m src.ui.start_ui 8222 -r 8555

wait
