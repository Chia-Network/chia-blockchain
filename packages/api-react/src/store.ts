import { configureStore, ConfigureStoreOptions } from '@reduxjs/toolkit';
import { TypedUseSelectorHook, useDispatch, useSelector } from 'react-redux';
import apiReducer from './slices/api';
import api from './api';

export function createStore(options?: ConfigureStoreOptions['preloadedState']) {
  return configureStore({
    reducer: {
      [api.reducerPath]: api.reducer,
      api: apiReducer,
    },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        serializableCheck: false,
      }).concat(
        api.middleware,
      ),
    ...options,
  });
}

export const store = createStore();

export type AppDispatch = typeof store.dispatch;
export const useAppDispatch = () => useDispatch<AppDispatch>();
export type RootState = ReturnType<typeof store.getState>;
export const useTypedSelector: TypedUseSelectorHook<RootState> = useSelector;
