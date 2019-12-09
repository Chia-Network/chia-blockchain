. .venv/bin/activate
. scripts/common.sh

echo "Starting local blockchain simulation. Make sure full node is configured to point to the local introducer (127.0.0.1:8445) in config/config.py."
echo "Note that this simulation will not work if connected to external nodes."

# Starts a harvester, farmer, timelord, introducer, and 3 full nodes, locally.
# Make sure to point the full node in config/config.yaml to the local introducer: 127.0.0.1:8445.
# Please note that the simulation is meant to be run locally and not connected to external nodes.

_run_bg_cmd python -m src.server.start_harvester
_run_bg_cmd python -m src.server.start_timelord
_run_bg_cmd python -m src.server.start_farmer
_run_bg_cmd python -m src.server.start_introducer
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8444 -id 4 -f -t -u 8222
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8002 -id 5 -u 8223
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8005 -id 6
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8010 -id 7
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8011 -id 8
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8012 -id 9
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8013 -id 10
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8014 -id 11
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8015 -id 12
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8016 -id 13
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8017 -id 14
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8018 -id 15
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8019 -id 16
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8020 -id 17
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8021 -id 18
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8022 -id 19
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8023 -id 20
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8024 -id 21
_run_bg_cmd python -m src.server.start_full_node "127.0.0.1" 8025 -id 22

wait