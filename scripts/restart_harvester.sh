echo "Shutting down harvesters"

_kill_harvester_servers() {
  PROCS=`ps -e | grep -E 'chia_harvester' | awk '!/grep/' | awk '{print $1}'`
  if [ -n "$PROCS" ]; then
    echo "$PROCS" | xargs -L1 kill
  fi
}

_kill_harvester_servers

BG_PIDS=""
_run_bg_cmd() {
  "$@" &
  BG_PIDS="$BG_PIDS $!"
}

echo "Restarting harvesters"

_run_bg_cmd python -m src.server.start_harvester

_term() {
  echo "Caught TERM or INT signal, killing all servers."
  for PID in $BG_PIDS; do
    kill -TERM "$PID"
  done
  _kill_servers
}

trap _term TERM
trap _term INT
