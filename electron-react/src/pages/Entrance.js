import React, { useEffect } from 'react';
import { connect } from 'react-redux';
import { newMessage } from '../modules/message';

const Entrance = ({ dispatch, connected }) => {
  const con_status = connected ? "connected" : "not connected"
  return (
    <div style={{ overflow: 'hidden' }}>
      {con_status}
    </div>
  );
};

const s2p = state => ({
  connected: state.websocket.connected,
});

export default connect(s2p)(Entrance);
