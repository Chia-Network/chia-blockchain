import React from "react";
import CssBaseline from "@material-ui/core/CssBaseline";
import List from '@material-ui/core/List';
import ListItem from '@material-ui/core/ListItem';
import ListItemText from '@material-ui/core/ListItemText';
import ListItemSecondaryAction from '@material-ui/core/ListItemSecondaryAction';
import DeleteIcon from '@material-ui/icons/Delete';
import IconButton from '@material-ui/core/IconButton';
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import logo from "../assets/img/chia_logo.svg"; // Tell webpack this JS file uses this image
import { withRouter, Redirect } from "react-router-dom";
import { connect, useSelector, useDispatch } from "react-redux";
import { Dialog } from '@material-ui/core';
import { log_in, delete_key } from "../modules/message";
import Link from "@material-ui/core/Link";
import Button from "@material-ui/core/Button";
import { Link as RouterLink } from "react-router-dom";

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
  textField: {
    borderColor: "#ffffff"
  },
  topButton: {
    height: 45,
    marginTop: theme.spacing(5),
    marginBottom: theme.spacing(1)
  },
  logo: {
    marginTop: theme.spacing(8),
    marginBottom: theme.spacing(3)
  },
  main: {
    height: "100%"
  },
  whiteText: {
    color: "white"
  },
  demo: {
    backgroundColor: theme.palette.background.paper,
  },
}));

const SelectKey = () => {
  const dispatch = useDispatch();
  const classes = useStyles();
  const logged_in = useSelector(state => state.wallet_state.logged_in);
  const connected_websocket = useSelector(state => state.websocket.connected);
  const public_key_fingerprints = useSelector(state => state.wallet_state.public_key_fingerprints);
  if (!connected_websocket || public_key_fingerprints.length == 0) {
    return <Redirect to="/" />;
  }
  if (logged_in) {
    return <Redirect to="/dashboard" />;
  }

  const handleClick = (fingerprint) => {
    return () => dispatch(log_in(fingerprint))
  }

  const handleDelete = (fingerprint) => {
    return () => {
      dispatch(delete_key(fingerprint));
    }
  }

  const list_items = public_key_fingerprints.map((fingerprint) => {
    return (
      <ListItem
              button
              onClick={handleClick(fingerprint[0])}
              key={fingerprint[0].toString() + (fingerprint[1] ? "has_seed" : "no_seed")}
          >
        <ListItemText
          primary={"Private key with public fingerprint " + fingerprint[0].toString()}
          secondary={fingerprint[1] ? "Can be backed up to mnemonic seed" : "Raw key, cannot be backed up"}
        />
        <ListItemSecondaryAction>
        <IconButton edge="end" aria-label="delete" onClick={handleDelete(fingerprint[0])}>
          <DeleteIcon />
        </IconButton>
      </ListItemSecondaryAction>
     </ListItem>)
  })

  return (
    <div className={classes.root}>
      <Container className={classes.main} component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <img className={classes.logo} src={logo} alt="Logo" />
          <h2 className={classes.whiteText}>Select Key</h2>
          <div className={classes.demo}>
            <List dense={classes.dense}>
              {list_items}
            </List>

          </div>
            <Link component={RouterLink} to="/Mnemonics">
              <Button
                type="submit"
                fullWidth
                variant="contained"
                color="primary"
                className={classes.topButton}
              >
                Import key from mnemonics
              </Button>
            </Link>
        </div>
      </Container>
    </div>
  );
};

export default withRouter(connect()(SelectKey));
