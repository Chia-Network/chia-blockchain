. .venv/bin/activate
. scripts/common.sh

# Starts a harvester, farmer, and full node.

_run_bg_cmd python -m src.server.start_harvester
_run_bg_cmd python -m src.server.start_farmer
_run_bg_cmd python -m src.server.start_full_node 8444 -id 1 -f -u 8222

wait
