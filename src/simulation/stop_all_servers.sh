ps -e | grep python | grep "start_" | awk '{print $1}' | xargs -L1  kill -9
ps -e | grep "fast_vdf/server" | awk '{print $1}' | xargs -L1  kill -9
