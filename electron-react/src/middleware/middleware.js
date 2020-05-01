import * as actions from '../modules/websocket';
import { newMessage, format_message, get_balance_for_wallet } from '../modules/message';

const socketMiddleware = () => {
  let socket = null;

  const onOpen = store => (event) => {
    store.dispatch(actions.wsConnected(event.target.url));
    var action = format_message("start_server", "{wallet_id: 1}")
    store.dispatch(action);
    var get_balance = get_balance_for_wallet(1)
    store.dispatch(get_balance)
  };

  const onClose = store => () => {
    store.dispatch(actions.wsDisconnected());
  };

  const onMessage = store => (event) => {
    const payload = JSON.parse(event.data);
    console.log(payload)
    switch (payload.type) {
      case 'balance':
        store.dispatch(newMessage(payload.msg));
        break;
      default:
        console.log(payload);
        break;
    }
  };

  return store => next => (action) => {
    switch (action.type) {
      case 'WS_CONNECT':
        if (socket !== null) {
          socket.close();
        }

        // connect to the remote host
        socket = new WebSocket(action.host);

        // websocket handlers
        socket.onmessage = onMessage(store);
        socket.onclose = onClose(store);
        socket.onopen = onOpen(store);

        break;
      case 'WS_DISCONNECT':
        if (socket !== null) {
          socket.close();
        }
        socket = null;
        break;
      case 'NEW_MESSAGE':
        socket.send(JSON.stringify({ command: action.command, data: action.data }));
        break;
      default:
        return next(action);
    }
  };
};

export default socketMiddleware();
