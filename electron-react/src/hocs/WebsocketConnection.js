import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { wsConnect } from '../modules/websocket';

const WebSocketConnection = (props) => {

  const dispatch = useDispatch()

  useEffect(() => {
    const { host } = props;
    dispatch(wsConnect(host))

  }, []);


  return props.children;
}

export default WebSocketConnection;