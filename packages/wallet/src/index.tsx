import './polyfill';
import './config/env';
import React from 'react';
import ReactDOM from 'react-dom';
import './config/env';
import AppRouter from './components/app/AppRouter';

ReactDOM.render(<AppRouter />, document.querySelector('#root'));
