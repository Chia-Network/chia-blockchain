import reduxThunk from 'redux-thunk';
import { createHashHistory } from 'history';
import { createStore, applyMiddleware, compose } from 'redux';
import { routerMiddleware } from 'connected-react-router';
import isElectron from 'is-electron';
import { createRootReducer } from './rootReducer';
import wsMiddleware from '../middleware/middleware';
import dev_config from '../dev_config';

export const history = createHashHistory();

const middlewares = [reduxThunk, wsMiddleware, routerMiddleware(history)];
const rootReducer = createRootReducer(history);
const initialState = {};

const store =
  isElectron() && !dev_config.redux_tool
    ? createStore(
        rootReducer,
        initialState,
        compose(applyMiddleware(...middlewares)),
      )
    : createStore(
        rootReducer,
        initialState,
        compose(
          applyMiddleware(...middlewares) /* preloadedState, */,
          (window.__REDUX_DEVTOOLS_EXTENSION_COMPOSE__ &&
            window.__REDUX_DEVTOOLS_EXTENSION_COMPOSE__()) ||
            compose,
        ),
      );

export default store;
