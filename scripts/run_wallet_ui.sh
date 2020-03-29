. ./activate

# Starts a wallet UI
chia-websocket-server &
npm run --prefix ./src/electron-ui start

wait
