. .venv/bin/activate
. scripts/common.sh

# Starts a harvester, farmer, timelord, introducer, and 3 full nodes.

_run_bg_cmd python -m src.server.start_harvester
_run_bg_cmd python -m src.server.start_timelord
_run_bg_cmd python -m src.server.start_farmer
_run_bg_cmd python -m src.server.start_introducer
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8444 -id 1 -f -t -u 8222
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8002 -id 2
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8005 -id 3

wait
