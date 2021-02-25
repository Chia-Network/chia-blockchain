import { useDispatch, useSelector } from 'react-redux';
import { wsConnect, wsConnecting } from '../modules/websocket';

const WebSocketConnection = (props) => {
  const dispatch = useDispatch();
  const connected = useSelector((state) => state.websocket.connected);
  const connecting = useSelector((state) => state.websocket.connecting);

  if (!connected && !connecting) {
    dispatch(wsConnecting());
    const { host } = props;
    dispatch(wsConnect(host));
  }

  return props.children;
};

export default WebSocketConnection;
