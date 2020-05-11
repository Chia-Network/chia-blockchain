import React from 'react';
import Button from '@material-ui/core/Button';
import CssBaseline from '@material-ui/core/CssBaseline';
import Grid from '@material-ui/core/Grid';
import { makeStyles } from '@material-ui/core/styles';
import Container from '@material-ui/core/Container';
import logo from '../assets/img/chia_logo.svg'; // Tell webpack this JS file uses this image
import { withRouter, Redirect } from 'react-router-dom'
import { connect, useSelector } from 'react-redux';
import Link from '@material-ui/core/Link';
import { Link as RouterLink } from 'react-router-dom';


const useStyles = makeStyles((theme) => ({
  root: {
    background: 'linear-gradient(45deg, #181818 30%, #333333 90%)',
    height:'100%',
    },
  paper: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    height: '100%',
  },
  form: {
    width: '100%', // Fix IE 11 issue.
    marginTop: theme.spacing(5),
  },
  textField: {
      borderColor: "#ffffff"
  },
  topButton: {
    height: 45,
    marginTop: theme.spacing(15),
    marginBottom: theme.spacing(1),
  },
  lowerButton: {
    height: 45,
    marginTop: theme.spacing(1),
    marginBottom: theme.spacing(3),
  },
  logo: {
    marginTop: theme.spacing(8),
    marginBottom: theme.spacing(3),
  },
  main: {
    height: '100%'
  }
}));

const SignIn = () => {
  const classes = useStyles();
  const logged_in = useSelector(state => state.wallet_state.logged_in)
  if (logged_in) {
      console.log("Redirecting to wallet")
      return (<Redirect to="/dashboard" />)
  }
  return (
    <div className={classes.root}>
    <Container className={classes.main} component="main" maxWidth="xs" >
      <CssBaseline />
      <div className={classes.paper}>
      <img className ={classes.logo} src={logo} alt="Logo" />;
      <div>
        <Link component={RouterLink} to="/Mnemonics">
            <Button
                type="submit"
                fullWidth
                variant="contained"
                color="primary"
                className={classes.topButton}
            >
                Enter Mnemonics
            </Button>
          </Link>
          <Link component={RouterLink} to="/CreateMnemonics">
            <Button
                type="submit"
                fullWidth
                variant="contained"
                color="primary"
                className={classes.lowerButton}
            >
                Generate New Keys
            </Button>
          </Link>
          </div>
          <Grid container>
            <Grid item xs>

            </Grid>
            <Grid item>
              <Link href="/Mnemonics" variant="body2">
                {"Run Full Node without keys"}
              </Link>
            </Grid>
          </Grid>
      </div>
    </Container>
    </div>
  );
}

export default withRouter(connect()(SignIn));
