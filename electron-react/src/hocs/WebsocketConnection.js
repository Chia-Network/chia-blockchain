import React, { Component } from 'react';
import { connect } from 'react-redux';
import { wsConnect } from '../modules/websocket';

class WebSocketConnection extends Component {
  componentDidMount() {
    const { dispatch, host } = this.props;
      dispatch(wsConnect(host))
  }

  render() {
    return this.props.children;
  }
}


export default connect()(WebSocketConnection);