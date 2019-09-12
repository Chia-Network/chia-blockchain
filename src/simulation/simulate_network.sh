python -m src.server.start_plotter &
P1=$!
python -m src.server.start_timelord &
P2=$!
python -m src.server.start_farmer &
P3=$!
python -m src.server.start_full_node "127.0.0.1" 8002 &
P4=$!
python -m src.server.start_full_node "127.0.0.1" 8004 &
P5=$!
python -m src.server.start_full_node "127.0.0.1" 8005 &
P6=$!
wait $P1 $P2 $P3 $P4 $P5 $P6
