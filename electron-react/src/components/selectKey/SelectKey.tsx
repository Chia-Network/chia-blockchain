import React, { useState } from "react";
import { useSelector, useDispatch } from "react-redux";
import { Container, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Tooltip, List, ListItem, ListItemText, IconButton } from "@material-ui/core";
import ListItemSecondaryAction from "@material-ui/core/ListItemSecondaryAction";
import { Delete as DeleteIcon, Visibility as VisibilityIcon } from "@material-ui/icons";
import Button from '../button/Button';
import { makeStyles } from "@material-ui/core/styles";
import logo from "../../assets/img/chia_logo.svg";
import LayoutHero from '../layout/LayoutHero';
import {
  login_action,
  delete_key,
  get_private_key,
  selectFingerprint,
  delete_all_keys,
} from "../../modules/message";
import Link from '../router/Link';
import {
  changeEntranceMenu,
  presentOldWallet,
  presentNewWallet
} from "../../modules/entranceMenu";
import { resetMnemonic } from "../../modules/mnemonic";
import { RootState } from "../../modules/rootReducer";

const useStyles = makeStyles(theme => ({
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

export default function SelectKey() {
  const dispatch = useDispatch();
  const classes = useStyles();
  const public_key_fingerprints = useSelector(
    (state: RootState) => state.wallet_state.public_key_fingerprints
  );

  const [open, setOpen] = useState(false);

  const handleClick = (fingerprint: string) => {
    return () => {
      dispatch(resetMnemonic());
      dispatch(selectFingerprint(fingerprint));
      dispatch(login_action(fingerprint));
    };
  };

  const handleClickOpen = () => {
    setOpen(true);
  };

  const handleClose = () => {
    setOpen(false);
  };

  const handleCloseDelete = () => {
    handleClose();
    dispatch(delete_all_keys());
  };

  const showKey = (fingerprint: string) => {
    return () => dispatch(get_private_key(fingerprint));
  };

  const handleDelete = (fingerprint: string) => {
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
        onClick={handleClick(fingerprint)}
        key={fingerprint.toString()}
      >
        <ListItemText
          className={classes.rightPadding}
          primary={`Private key with public fingerprint ${fingerprint.toString()}`}
          secondary="Can be backed up to mnemonic seed"
        />
        <ListItemSecondaryAction>
          <Tooltip title="See private key">
            <IconButton
              edge="end"
              aria-label="delete"
              onClick={showKey(fingerprint)}
            >
              <VisibilityIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="DANGER: permanantly delete private key">
            <IconButton
              edge="end"
              aria-label="delete"
              onClick={handleDelete(fingerprint)}
            >
              <DeleteIcon />
            </IconButton>
          </Tooltip>
        </ListItemSecondaryAction>
      </ListItem>
    );
  });

  return (
    <LayoutHero>
      <Container component="main" maxWidth="xs">
        <div className={classes.paper}>
          <img className={classes.logo} src={logo} alt="Logo" />
          {public_key_fingerprints && public_key_fingerprints.length > 0 ? (
            <h1 className={classes.whiteText}>Select Key</h1>
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
            <List>{list_items}</List>
          </div>
          <Link onClick={goToMnemonics} to="/mnemonics" fullWidth>
            <Button
              type="submit"
              variant="contained"
              color="primary"
              size="large"
              fullWidth
            >
              Import from Mnemonics (24 words)
            </Button>
          </Link>
          <Link onClick={goToNewWallet} to="/wallet" fullWidth>
            <Button
              type="submit"
              variant="contained"
              color="primary"
              fullWidth
            >
              Create a new private key
            </Button>
          </Link>
          <Button
            onClick={handleClickOpen}
            type="submit"
            variant="contained"
            color="danger"
            fullWidth
          >
            Delete all keys
          </Button>
        </div>
      </Container>
      <Dialog
        open={open}
        onClose={handleClose}
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
      >
        <DialogTitle id="alert-dialog-title">
          Delete all keys
        </DialogTitle>
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
    </LayoutHero>
  );
}
