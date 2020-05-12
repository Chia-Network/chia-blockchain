import reduxThunk from 'redux-thunk';
import { createStore, applyMiddleware, compose } from 'redux';
import rootReducer from './reducers';
import wsMiddleware from '../middleware/middleware';
import isElectron from 'is-electron'

const middleware = [reduxThunk, wsMiddleware];


const store = isElectron() ? createStore(
  rootReducer,
  compose(
    applyMiddleware(...middleware),
  ),
) : createStore(
  rootReducer,
  compose(
    applyMiddleware(...middleware),
    window.__REDUX_DEVTOOLS_EXTENSION__ && window.__REDUX_DEVTOOLS_EXTENSION__(),
  ),
);

export default store;
