. .venv/bin/activate
. scripts/common.sh

echo "Starting local blockchain simulation. Runs a local introducer and chia system."
echo "Note that this simulation will not work if connected to external nodes."

# Starts a harvester, farmer, timelord, introducer, and 3 full nodes, locally.
# Make sure to point the full node in config/config.yaml to the local introducer: 127.0.0.1:8445.
# Please note that the simulation is meant to be run locally and not connected to external nodes.

_run_bg_cmd python -m src.server.start_harvester
_run_bg_cmd python -m src.server.start_timelord
_run_bg_cmd python -m src.server.start_farmer
_run_bg_cmd python -m src.server.start_introducer
_run_bg_cmd python -m src.server.start_full_node --port=8444 --database_path="simulation_1.db" --connect_to_farmer=True --connect_to_timelord=True --rpc_port=8555 --introducer_peer.host="127.0.0.1" --introducer_peer.port=8445
_run_bg_cmd python -m src.server.start_full_node --port=8002 --database_path="simulation_2.db" --rpc_port=8556 --introducer_peer.host="127.0.0.1" --introducer_peer.port=8445
_run_bg_cmd python -m src.ui.start_ui --port=8222 --rpc_port=8555
_run_bg_cmd python -m src.ui.start_ui --port=8223 --rpc_port=8556

wait