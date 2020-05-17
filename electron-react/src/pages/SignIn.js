import React from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import logo from "../assets/img/chia_logo.svg"; // Tell webpack this JS file uses this image
import { withRouter } from "react-router-dom";
import { connect, useDispatch } from "react-redux";
import Link from "@material-ui/core/Link";
import {
  changeEntranceMenu,
  presentOldWallet,
  presentNewWallet
} from "../modules/entranceMenu";

const useStyles = makeStyles(theme => ({
  root: {
    background: "linear-gradient(45deg, #181818 30%, #333333 90%)",
    height: "100%"
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    height: "100%"
  },
  form: {
    width: "100%", // Fix IE 11 issue.
    marginTop: theme.spacing(5)
  },
  textField: {
    borderColor: "#ffffff"
  },
  topButton: {
    height: 45,
    marginTop: theme.spacing(15),
    marginBottom: theme.spacing(1)
  },
  lowerButton: {
    height: 45,
    marginTop: theme.spacing(1),
    marginBottom: theme.spacing(3)
  },
  logo: {
    marginTop: theme.spacing(8),
    marginBottom: theme.spacing(3)
  },
  warning: {
    color: "red"
  },
  main: {
    height: "100%"
  }
}));

const SignIn = () => {
  const classes = useStyles();
  const dispatch = useDispatch();

  function go_new_wallet() {
    dispatch(changeEntranceMenu(presentNewWallet));
  }

  function go_old_wallet() {
    dispatch(changeEntranceMenu(presentOldWallet));
  }

  return (
    <div className={classes.root}>
      <Container className={classes.main} component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <img className={classes.logo} src={logo} alt="Logo" />
          <div>
            <Button
              onClick={go_old_wallet}
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.topButton}
            >
              Enter Mnemonics
            </Button>
            <Button
              onClick={go_new_wallet}
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.lowerButton}
            >
              Generate New Keys
            </Button>
          </div>
          <Grid container>
            <Grid item xs></Grid>
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
};

export default withRouter(connect()(SignIn));
