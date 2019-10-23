ps -e | grep python | grep "start_" | awk '{print $1}' | xargs -L1  kill -9
ps -e | grep "fast_vdf/server" | awk '{print $1}' | xargs -L1  kill -9

./lib/chiavdf/fast_vdf/server 8889 &
P1=$!
./lib/chiavdf/fast_vdf/server 8890 &
P2=$!
python -m src.server.start_plotter &
P3=$!
python -m src.server.start_timelord &
P4=$!
python -m src.server.start_farmer &
P5=$!
python -m src.server.start_full_node "127.0.0.1" 8002 "-f" "-t" &
P6=$!
# python -m src.server.start_full_node "127.0.0.1" 8004 "-t" &
# P7=$!
python -m src.server.start_full_node "127.0.0.1" 8005 &
P8=$!

_term() {
  echo "Caught SIGTERM signal, killing all servers."
  kill -TERM "$P1" 2>/dev/null
  kill -TERM "$P2" 2>/dev/null
  kill -TERM "$P3" 2>/dev/null
  kill -TERM "$P4" 2>/dev/null
  kill -TERM "$P5" 2>/dev/null
  kill -TERM "$P6" 2>/dev/null
  kill -TERM "$P7" 2>/dev/null
  kill -TERM "$P8" 2>/dev/null
}

trap _term SIGTERM
trap _term SIGINT
trap _term INT
wait $P1 $P2 $P3 $P4 $P5 $P6 $P7 $P8