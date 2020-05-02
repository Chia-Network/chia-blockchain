import React from 'react';
import { Switch, Route } from 'react-router-dom';
import { connect } from 'react-redux';
import Entrance from './pages/Entrance';
import SignIn from './pages/SignIn';
import CreateMnemonics from './pages/CreateMnemonics'
import Mnemonics from './pages/Mnemonics'
import { createMuiTheme, ThemeProvider } from '@material-ui/core/styles';
import purple from '@material-ui/core/colors/purple';
import green from '@material-ui/core/colors/green';

const theme = createMuiTheme({
  palette: {
    primary: { main: '#ffffff', contrastText: '#000000' },
    secondary: { main: '#000000', contrastText: '#ffffff' }
  },
  root: {
    background: 'linear-gradient(45deg, #142229 30%, #112240 90%)',
    height:'100%',
  },
});

const App = () => (
  <React.Fragment>
    <Switch>
    <ThemeProvider theme={theme}>
      <Route exact path="/" component={SignIn} />
      <Route exact path="/CreateMnemonics" component={CreateMnemonics} />
      <Route exact path="/Mnemonics" component={Mnemonics} />
    </ThemeProvider>
    </Switch>
  </React.Fragment>
);

export default connect()(App);
