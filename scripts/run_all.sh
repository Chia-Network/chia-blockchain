. .venv/bin/activate
. scripts/common.sh

# Starts a harvester, farmer, timelord, introducer and full node

_run_bg_cmd python -m src.server.start_harvester
_run_bg_cmd python -m src.server.start_timelord
_run_bg_cmd python -m src.server.start_farmer
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8444 -id 1 -f -t -u 8222

wait
