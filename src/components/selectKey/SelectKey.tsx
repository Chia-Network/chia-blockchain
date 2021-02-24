import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector, useDispatch } from 'react-redux';
import styled from 'styled-components';
import { ConfirmDialog, Flex, Button, Link, Logo } from '@chia/core';
import {
  Card,
  Typography,
  Container,
  Tooltip,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
} from '@material-ui/core';
import {
  Delete as DeleteIcon,
  Visibility as VisibilityIcon,
} from '@material-ui/icons';
import LayoutHero from '../layout/LayoutHero';
import {
  login_action,
  delete_key,
  get_private_key,
  selectFingerprint,
  delete_all_keys,
} from '../../modules/message';
import { resetMnemonic } from '../../modules/mnemonic';
import type { RootState } from '../../modules/rootReducer';
import type Fingerprint from '../../types/Fingerprint';
import useOpenDialog from '../../hooks/useOpenDialog';

const StyledFingerprintListItem = styled(ListItem)`
  padding-right: ${({ theme }) => `${theme.spacing(11)}px`};
`;

export default function SelectKey() {
  const dispatch = useDispatch();
  const openDialog = useOpenDialog();
  const publicKeyFingerprints = useSelector(
    (state: RootState) => state.wallet_state.public_key_fingerprints,
  );
  const hasFingerprints =
    publicKeyFingerprints && !!publicKeyFingerprints.length;

  function handleClick(fingerprint: Fingerprint) {
    dispatch(resetMnemonic());
    dispatch(selectFingerprint(fingerprint));
    dispatch(login_action(fingerprint));
  }

  function handleShowKey(fingerprint: Fingerprint) {
    dispatch(get_private_key(fingerprint));
  }

  async function handleDeletePrivateKey(fingerprint: Fingerprint) {
    const deletePrivateKey = await openDialog((
      <ConfirmDialog
        title={<Trans>Delete key</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        cancelTitle={<Trans>Back</Trans>}
        confirmColor="default"
      >
        <Trans>
          Deleting the key will permanently remove the key from your computer,
          make sure you have backups. Are you sure you want to continue?
        </Trans>
      </ConfirmDialog>
    ));

    // @ts-ignore
    if (deletePrivateKey) {
      dispatch(delete_key(fingerprint));
    }
  }

  async function handleDeleteAllKeys() {
    const deleteAllKeys = await openDialog((
      <ConfirmDialog
        title={<Trans>Delete all keys</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        cancelTitle={<Trans>Back</Trans>}
        confirmColor="default"
      >
        <Trans>
          Deleting all keys will permanently remove the keys from your
          computer, make sure you have backups. Are you sure you want to
          continue?
        </Trans>
      </ConfirmDialog>
    ));

    // @ts-ignore
    if (deleteAllKeys) {
      dispatch(delete_all_keys());
    }
  }

  return (
    <LayoutHero>
      <Container maxWidth="xs">
        <Flex flexDirection="column" alignItems="center" gap={3}>
          <Logo width={130} />
          {hasFingerprints ? (
            <Typography variant="h5" component="h1" gutterBottom>
              <Trans>Select Key</Trans>
            </Typography>
          ) : (
            <>
              <Typography variant="h5" component="h1" gutterBottom>
                <Trans>Sign In</Trans>
              </Typography>
              <Typography variant="subtitle1">
                <Trans>
                  Welcome to Chia. Please log in with an existing key, or create
                  a new key.
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
                          <Trans>
                            Private key with public fingerprint {fingerprint}
                          </Trans>
                        }
                        secondary={
                          <Trans>
                            Can be backed up to mnemonic seed
                          </Trans>
                        }
                      />
                      <ListItemSecondaryAction>
                        <Tooltip title={<Trans>See private key</Trans>}>
                          <IconButton
                            edge="end"
                            aria-label="show"
                            onClick={() => handleShowKey(fingerprint)}
                          >
                            <VisibilityIcon />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title={<Trans>DANGER: permanently delete private key</Trans>}>
                          <IconButton
                            edge="end"
                            aria-label="delete"
                            onClick={() => handleDeletePrivateKey(fingerprint)}
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
                <Trans>
                  Create a new private key
                </Trans>
              </Button>
            </Link>
            <Link to="/wallet/import">
              <Button type="submit" variant="contained" size="large" fullWidth>
                <Trans>
                  Import from Mnemonics (24 words)
                </Trans>
              </Button>
            </Link>
            <Button
              onClick={handleDeleteAllKeys}
              type="submit"
              variant="contained"
              color="danger"
              size="large"
              fullWidth
            >
              <Trans>Delete all keys</Trans>
            </Button>
          </Flex>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
