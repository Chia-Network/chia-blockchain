import './polyfill';
import React from 'react';
import ReactDOM from 'react-dom';
import './config/env';
import App from './components/app/App';

ReactDOM.render(<App />, document.querySelector('#root'));
