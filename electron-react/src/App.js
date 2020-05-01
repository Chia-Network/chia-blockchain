import React from 'react';
import { Switch, Route } from 'react-router-dom';
import { connect } from 'react-redux';
import Entrance from './pages/Entrance';

const App = () => (
  <React.Fragment>
    <Switch>
      <Route exact path="/" component={Entrance} />
    </Switch>
  </React.Fragment>
);

export default connect()(App);
