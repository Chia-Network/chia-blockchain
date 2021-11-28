import React from 'react';
import { useSelector } from 'react-redux';
import { Route, Navigate, RouteProps } from 'react-router-dom';
// import type { RootState } from '../../../../modules/rootReducer';

type RootState = any;
type Props = RouteProps;

export default function PrivateRoute(props: Props) {
  /*
  const loggedIn = useSelector(
    (state: RootState) => state.wallet_state.logged_in,
  );
  if (!loggedIn) {
    return <Redirect to="/" />;
  }
  */

  return <Route {...props} />;
}
