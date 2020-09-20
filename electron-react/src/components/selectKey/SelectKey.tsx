import React, { useState } from "react";
import { useSelector, useDispatch } from "react-redux";
import { Card, Typography, Container, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Tooltip, List, ListItem, ListItemText, IconButton } from "@material-ui/core";
import ListItemSecondaryAction from "@material-ui/core/ListItemSecondaryAction";
import { Delete as DeleteIcon, Visibility as VisibilityIcon } from "@material-ui/icons";
import Button from '../button/Button';
import { makeStyles } from "@material-ui/core/styles";
import LayoutHero from '../layout/LayoutHero';
import Flex from '../flex/Flex';
import Logo from '../logo/Logo';
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
import type { RootState } from "../../modules/rootReducer";

const useStyles = makeStyles(theme => ({
  centeredSpan: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
  },
  textField: {
    borderColor: "#ffffff"
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
  const publicKeyFingerprints = useSelector(
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

  const hasFingerprints = publicKeyFingerprints && !!publicKeyFingerprints.length;

  return (
    <LayoutHero>
      <Container maxWidth="xs">
        <Flex flexDirection="column" alignItems="center" gap={3}>
          <Logo />
          {hasFingerprints ? (
            <h1 className={classes.whiteText}>Select Key</h1>
          ) : (
            <>
              <Typography variant="h5" component="h1" color="primary" gutterBottom>
                Sign In
              </Typography>
              <Typography variant="subtitle1">
                Welcome to Chia. Please log in with an existing key, or create a
                a new key.
              </Typography>
            </>
          )}
          <Flex flexDirection="column" gap={3} alignItems="stretch" alignSelf="stretch">
            {hasFingerprints && (
              <Card>
                <List>
                  {publicKeyFingerprints.map((fingerprint) => (
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
                ))}
                </List>
              </Card>
            )}
            <Link onClick={goToMnemonics} to="/mnemonics">
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
            <Link to="/wallet">
              <Button
                type="submit"
                variant="contained"
                color="primary"
                size="large"
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
              size="large"
              fullWidth
            >
              Delete all keys
            </Button>
          </Flex>
        </Flex>
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
