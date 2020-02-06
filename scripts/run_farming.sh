. .venv/bin/activate
. scripts/common.sh

# Starts a harvester, farmer, and full node.

_run_bg_cmd python -m src.server.start_harvester
_run_bg_cmd python -m src.server.start_farmer
_run_bg_cmd python -m src.server.start_full_node --port=8444 --connect_to_farmer=True --rpc_port=8555
_run_bg_cmd python -m src.ui.start_ui --port=8222 --rpc_port=8555

wait
