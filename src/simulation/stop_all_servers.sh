ps -e | grep python | grep "start_" | awk '{print $1}' | xargs -L1  kill -9
