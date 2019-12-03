. .venv/bin/activate
. scripts/common.sh

echo "Starting local blockchain simulation. Make sure full node is configured to point to the local introducer (127.0.0.1:8445) in config/config.py."
echo "Note that this simulation will not work if connected to external nodes."

# Starts a harvester, farmer, timelord, introducer, and 3 full nodes, locally.
# Make sure to point the full node in config/config.yaml to the local introducer: 127.0.0.1:8444.
# Please note that the simulation is meant to be run locally and not connected to external nodes.

_run_bg_cmd python -m src.server.start_harvester
_run_bg_cmd python -m src.server.start_timelord
_run_bg_cmd python -m src.server.start_farmer
_run_bg_cmd python -m src.server.start_introducer
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8444 -id 1 -f -t -u 8222
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8002 -id 2 -u 8223
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8005 -id 3 -u 8224

wait