. .venv/bin/activate
. scripts/common.sh

# Starts a full node and a wallet

_run_bg_cmd python -m src.server.start_full_node --port=8444 --connect_to_farmer=True --rpc_port=8555
_run_bg_cmd python -m src.server.start_wallet


wait