import React from 'react';
import { Switch, Route } from 'react-router-dom';
import { connect } from 'react-redux';
import SignIn from './pages/SignIn';
import NewWallet from './pages/NewWallet'
import OldWallet from './pages/OldWallet'
import Wallets from './pages/Wallets'
import Dashboard from './pages/Dashboard'

import { createMuiTheme, ThemeProvider } from '@material-ui/core/styles';
const defaultTheme = createMuiTheme();

const theme = createMuiTheme({
  palette: {
    primary: { main: '#ffffff', contrastText: '#000000' },
    secondary: { main: '#000000', contrastText: '#ffffff' }
  },
  root: {
    background: 'linear-gradient(45deg, #333333 30%, #333333 90%)',
    height: '100%',
  },
  app_root: {
    background: 'linear-gradient(45deg, #142229 30%, #112240 90%)',
    height: '100%',
  },
  paper: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  avatar: {
    marginTop: defaultTheme.spacing(8),
    backgroundColor: defaultTheme.palette.secondary.main,
  },
  form: {
    width: '100%',
    marginTop: defaultTheme.spacing(5),
  },
  textField: {
    borderColor: "#ffffff"
  },
  submit: {
    marginTop: defaultTheme.spacing(8),
    marginBottom: defaultTheme.spacing(3),
  },
  grid: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    paddingTop: defaultTheme.spacing(5),
  },
  grid_item: {
    paddingTop: 10,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    backgroundColor: "#444444",
    color: "#ffffff",
    height: 50,
    verticalAlign: 'middle',
  },
  title: {
    color: '#ffffff',
    marginTop: defaultTheme.spacing(4),
    marginBottom: defaultTheme.spacing(8),
  },
  navigator: {
    color: '#ffffff',
    marginTop: defaultTheme.spacing(4),
    marginLeft: defaultTheme.spacing(4),
    fontSize: 35,
  }
});

const App = () => {
  return (
    <React.Fragment>
      <ThemeProvider theme={theme}>
        <Switch>
          <Route exact path="/" component={SignIn} />
          <Route exact path="/CreateMnemonics" component={NewWallet} />
          <Route exact path="/Mnemonics" component={OldWallet} />
          <Route exact path="/dashboard" component={Dashboard} />
        </Switch>
      </ThemeProvider>
    </React.Fragment>
  )
}

export default connect()(App);
