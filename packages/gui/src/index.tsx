import './polyfill';
import './config/env';
import React from 'react';
import ReactDOM from 'react-dom';
import './config/env';
import App from './components/app/App';

// we need to use additional root for hot reloading
function Root() {
  return (
    <App />
  );
}

ReactDOM.render(<Root />, document.querySelector('#root'));
