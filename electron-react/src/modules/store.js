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

try {
  if (localStorage.getItem('plot_queue')) {
    initialState.plot_queue = JSON.parse(localStorage.getItem('plot_queue'));
  }
} catch {
  localStorage.removeItem('plot_queue');
}

try {
  if (localStorage.getItem('local_storage')) {
    initialState.local_storage = JSON.parse(
      localStorage.getItem('local_storage'),
    );
  }
} catch {
  localStorage.removeItem('local_storage');
}

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

store.subscribe(() => {
  const state = store.getState();
  if (state.plot_queue) {
    localStorage.setItem('plot_queue', JSON.stringify(state.plot_queue));
  }

  if (state.local_storage) {
    localStorage.setItem('local_storage', JSON.stringify(state.local_storage));
  }
});

export default store;
