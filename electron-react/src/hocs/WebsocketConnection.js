import { useDispatch, useSelector } from 'react-redux';
import { wsConnect, wsConnecting } from '../modules/websocket';

const WebSocketConnection = (props) => {
  const dispatch = useDispatch();
  const connected = useSelector((state) => state.websocket.connected);
  const connecting = useSelector((state) => state.websocket.connecting);
  let timeout = null;

  function connect() {
    timeout = setTimeout(() => {
      const { host } = props;
      dispatch(wsConnect(host));
    }, 300);
  }

  if (!timeout && !connected && !connecting) {
    dispatch(wsConnecting());
    connect();
  }

  return props.children;
};

export default WebSocketConnection;
