import React from "react";
import CssBaseline from "@material-ui/core/CssBaseline";
import List from "@material-ui/core/List";
import ListItem from "@material-ui/core/ListItem";
import ListItemText from "@material-ui/core/ListItemText";
import { Tooltip } from "@material-ui/core";
import ListItemSecondaryAction from "@material-ui/core/ListItemSecondaryAction";
import DeleteIcon from "@material-ui/icons/Delete";
import IconButton from "@material-ui/core/IconButton";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import logo from "../assets/img/chia_logo.svg"; // Tell webpack this JS file uses this image
import { withRouter } from "react-router-dom";
import { connect, useSelector, useDispatch } from "react-redux";
import {
  login_action,
  delete_key,
  get_private_key,
  selectFingerprint
} from "../modules/message";
import Link from "@material-ui/core/Link";
import Button from "@material-ui/core/Button";
import VisibilityIcon from "@material-ui/icons/Visibility";
import { delete_all_keys } from "../modules/message";
import Dialog from "@material-ui/core/Dialog";
import DialogActions from "@material-ui/core/DialogActions";
import DialogContent from "@material-ui/core/DialogContent";
import DialogContentText from "@material-ui/core/DialogContentText";
import DialogTitle from "@material-ui/core/DialogTitle";
import {
  changeEntranceMenu,
  presentOldWallet,
  presentNewWallet
} from "../modules/entranceMenu";
import { resetMnemonic } from "../modules/mnemonic_input";

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
  centeredSpan: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
  },
  textField: {
    borderColor: "#ffffff"
  },
  topButton: {
    width: 400,
    height: 45,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(1)
  },
  bottomButton: {
    width: 400,
    height: 45,
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(1)
  },
  bottomButtonRed: {
    width: 400,
    height: 45,
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(1),
    color: "red"
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
  whiteP: {
    color: "white",
    fontSize: "18px"
  },
  demo: {
    backgroundColor: theme.palette.background.paper
  },
  rightPadding: {
    paddingRight: theme.spacing(3)
  }
}));

const SelectKey = () => {
  const dispatch = useDispatch();
  const classes = useStyles();
  const public_key_fingerprints = useSelector(
    state => state.wallet_state.public_key_fingerprints
  );

  const [open, setOpen] = React.useState(false);

  const handleClick = fingerprint => {
    return () => {
      dispatch(resetMnemonic());
      dispatch(selectFingerprint(fingerprint));
      dispatch(login_action(fingerprint));
    };
  };

  const showKey = fingerprint => {
    return () => dispatch(get_private_key(fingerprint));
  };

  const handleDelete = fingerprint => {
    return () => dispatch(delete_key(fingerprint));
  };

  const goToMnemonics = () => {
    dispatch(changeEntranceMenu(presentOldWallet));
  };

  const goToNewWallet = () => {
    dispatch(changeEntranceMenu(presentNewWallet));
  };

  const list_items = public_key_fingerprints.map(fingerprint => {
    return (
      <ListItem
        button
        onClick={handleClick(fingerprint[0])}
        key={
          fingerprint[0].toString() + (fingerprint[1] ? "has_seed" : "no_seed")
        }
      >
        <ListItemText
          className={classes.rightPadding}
          primary={
            "Private key with public fingerprint " + fingerprint[0].toString()
          }
          secondary={
            fingerprint[1]
              ? "Can be backed up to mnemonic seed"
              : "Raw key, cannot be backed up"
          }
        />
        <ListItemSecondaryAction>
          <Tooltip title="See private key">
            <IconButton
              edge="end"
              aria-label="delete"
              onClick={showKey(fingerprint[0])}
            >
              <VisibilityIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="DANGER: permanantly delete private key">
            <IconButton
              edge="end"
              aria-label="delete"
              onClick={handleDelete(fingerprint[0])}
            >
              <DeleteIcon />
            </IconButton>
          </Tooltip>
        </ListItemSecondaryAction>
      </ListItem>
    );
  });

  return (
    <div className={classes.root}>
      <Container className={classes.main} component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <img className={classes.logo} src={logo} alt="Logo" />
          {public_key_fingerprints && public_key_fingerprints.length > 0 ? (
            <h2 className={classes.whiteText}>Select Key</h2>
          ) : (
            <span className={classes.centeredSpan}>
              <h2 className={classes.whiteText}>Sign In</h2>
              <p className={classes.whiteP}>
                Welcome to Chia. Please log in with an existing key, or create a
                a new key.
              </p>
            </span>
          )}
          <div className={classes.demo}>
            <List dense={classes.dense}>{list_items}</List>
          </div>
          <Link onClick={goToMnemonics}>
            <Button
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.topButton}
            >
              Import from Mnemonics (24 words)
            </Button>
          </Link>
          <Link onClick={goToNewWallet}>
            <Button
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.bottomButton}
            >
              Create a new private key
            </Button>
          </Link>
          <Link onClick={handleClickOpen}>
            <Button
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.bottomButtonRed}
            >
              Delete all keys
            </Button>
          </Link>
        </div>
      </Container>
      <Dialog
        open={open}
        onClose={handleClose}
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
      >
        <DialogTitle id="alert-dialog-title">{"Delete all keys"}</DialogTitle>
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            Deleting all keys will permanatly remove the keys from your
            computer, make sure you have backups. Are you sure you want to
            continue?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} color="secondary">
            Back
          </Button>
          <Button onClick={handleCloseDelete} color="secondary" autoFocus>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default withRouter(connect()(SelectKey));
