import React from 'react';
import ReactDOM from 'react-dom';
import { BrowserRouter as Router, Route } from 'react-router-dom';
import { Provider } from 'react-redux';
import App from './App';
import './assets/css/App.css';
import store from './modules/store';
import WebSocketConnection from './hocs/WebsocketConnection'
import Mnemonics from './pages/Mnemonics'
const Root = ({ store }) => (
  <Router>
      <Provider store={store}>
      <WebSocketConnection host={"ws://127.0.0.1:9256/"}>
        <Route path="/" component={App} />
        </WebSocketConnection>
      </Provider>
  </Router>
);

ReactDOM.render(<Root store={store} />, document.getElementById('root'));
