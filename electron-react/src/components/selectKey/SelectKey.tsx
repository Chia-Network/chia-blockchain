import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector, useDispatch } from 'react-redux';
import { useHistory } from 'react-router';
import styled from 'styled-components';
import {
  Card,
  Typography,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Tooltip,
  List,
  ListItem,
  ListItemText,
  IconButton,
} from '@material-ui/core';
import ListItemSecondaryAction from '@material-ui/core/ListItemSecondaryAction';
import {
  Delete as DeleteIcon,
  Visibility as VisibilityIcon,
} from '@material-ui/icons';
import Button from '../button/Button';
import LayoutHero from '../layout/LayoutHero';
import Flex from '../flex/Flex';
import Brand from '../brand/Brand';
import {
  login_action,
  delete_key,
  get_private_key,
  selectFingerprint,
  delete_all_keys,
} from '../../modules/message';
import Link from '../router/Link';
import { resetMnemonic } from '../../modules/mnemonic';
import type { RootState } from '../../modules/rootReducer';
import type Fingerprint from '../../types/Fingerprint';

const StyledFingerprintListItem = styled(ListItem)`
  padding-right: ${({ theme }) => `${theme.spacing(11)}px`};
`;

export default function SelectKey() {
  const history = useHistory();
  const dispatch = useDispatch();
  const [open, setOpen] = useState<boolean>(false);
  const publicKeyFingerprints = useSelector(
    (state: RootState) => state.wallet_state.public_key_fingerprints,
  );
  const hasFingerprints =
    publicKeyFingerprints && !!publicKeyFingerprints.length;

  async function handleClick(fingerprint: Fingerprint) {
    dispatch(resetMnemonic());
    dispatch(selectFingerprint(fingerprint));
    dispatch(login_action(fingerprint));
  }

  function handleClickOpen() {
    setOpen(true);
  }

  function handleClose() {
    setOpen(false);
  }

  function handleCloseDelete() {
    handleClose();
    dispatch(delete_all_keys());
  }

  function handleShowKey(fingerprint: Fingerprint) {
    dispatch(get_private_key(fingerprint));
  }

  function handleDelete(fingerprint: Fingerprint) {
    dispatch(delete_key(fingerprint));
  }

  return (
    <LayoutHero>
      <Container maxWidth="xs">
        <Flex flexDirection="column" alignItems="center" gap={3}>
          <Brand />
          {hasFingerprints ? (
            <Typography variant="h5" component="h1" gutterBottom>
              <Trans id="SelectKey.title">Select Key</Trans>
            </Typography>
          ) : (
            <>
              <Typography variant="h5" component="h1" gutterBottom>
                <Trans id="SelectKey.signInTitle">Sign In</Trans>
              </Typography>
              <Typography variant="subtitle1">
                <Trans id="SelectKey.signInDescription">
                  Welcome to Chia. Please log in with an existing key, or create
                  a a new key.
                </Trans>
              </Typography>
            </>
          )}
          <Flex
            flexDirection="column"
            gap={3}
            alignItems="stretch"
            alignSelf="stretch"
          >
            {hasFingerprints && (
              <Card>
                <List>
                  {publicKeyFingerprints.map((fingerprint: Fingerprint) => (
                    <StyledFingerprintListItem
                      onClick={() => handleClick(fingerprint)}
                      key={fingerprint}
                      button
                    >
                      <ListItemText
                        primary={
                          <Trans id="SelectKey.selectFingerprint">
                            Private key with public fingerprint {fingerprint}
                          </Trans>
                        }
                        secondary={
                          <Trans id="SelectKey.selectKeyCanBeBacked">
                            Can be backed up to mnemonic seed
                          </Trans>
                        }
                      />
                      <ListItemSecondaryAction>
                        <Tooltip title="See private key">
                          <IconButton
                            edge="end"
                            aria-label="show"
                            onClick={() => handleShowKey(fingerprint)}
                          >
                            <VisibilityIcon />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="DANGER: permanantly delete private key">
                          <IconButton
                            edge="end"
                            aria-label="delete"
                            onClick={() => handleDelete(fingerprint)}
                          >
                            <DeleteIcon />
                          </IconButton>
                        </Tooltip>
                      </ListItemSecondaryAction>
                    </StyledFingerprintListItem>
                  ))}
                </List>
              </Card>
            )}
            <Link to="/wallet/add">
              <Button
                type="submit"
                variant="contained"
                color="primary"
                size="large"
                fullWidth
              >
                <Trans id="SelectKey.createNewPrivateKey">
                  Create a new private key
                </Trans>
              </Button>
            </Link>
            <Link to="/wallet/import">
              <Button type="submit" variant="contained" size="large" fullWidth>
                <Trans id="SelectKey.importFromMnemonics">
                  Import from Mnemonics (24 words)
                </Trans>
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
              <Trans id="SelectKey.deleteAllKeys">Delete all keys</Trans>
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
          <Trans id="DeleteAllKeys.title">Delete all keys</Trans>
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            <Trans id="DeleteAllKeys.description">
              Deleting all keys will permanatly remove the keys from your
              computer, make sure you have backups. Are you sure you want to
              continue?
            </Trans>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} color="secondary" autoFocus>
            <Trans id="DeleteAllKeys.back">Back</Trans>
          </Button>
          <Button onClick={handleCloseDelete} color="secondary">
            <Trans id="DeleteAllKeys.delete">Delete</Trans>
          </Button>
        </DialogActions>
      </Dialog>
    </LayoutHero>
  );
}
