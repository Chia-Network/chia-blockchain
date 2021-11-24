import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector, useDispatch } from 'react-redux';
import styled from 'styled-components';
import { Button, ConfirmDialog, Flex, Logo } from '@chia/core';
import { Alert } from '@material-ui/lab';
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
  delete_all_keys,
  check_delete_key_action,
  skipKeyringMigration,
} from '../../modules/message';
import { resetMnemonic } from '../../modules/mnemonic';
import type { RootState } from '../../modules/rootReducer';
import type Fingerprint from '../../types/Fingerprint';
import useOpenDialog from '../../hooks/useOpenDialog';
import { openProgress, closeProgress } from '../../modules/progress';

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
  const needsKeyringMigration = useSelector(
    (state: RootState) => state.keyring_state.needs_migration
  );
  const skippedKeyringMigration = useSelector(
    (state: RootState) => state.keyring_state.migration_skipped
  );

  function handleClick(fingerprint: Fingerprint) {
    dispatch(resetMnemonic());
    dispatch(login_action(fingerprint));
  }

  function handleShowKey(fingerprint: Fingerprint) {
    dispatch(get_private_key(fingerprint));
  }

  async function handleDeletePrivateKey(e: React.MouseEvent<HTMLButtonElement>, fingerprint: Fingerprint) {
    const keyringCanBeModified = await handleKeyringMutator(e);

    if (keyringCanBeModified) {
      dispatch(openProgress());
      const response: any = await dispatch(check_delete_key_action(fingerprint));
      dispatch(closeProgress());

    const deletePrivateKey = await openDialog(
      <ConfirmDialog
        title={<Trans>Delete key {fingerprint}</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        cancelTitle={<Trans>Back</Trans>}
        confirmColor="danger"
      >
        {response.used_for_farmer_rewards && (<Alert severity="warning">
          <Trans>
            Warning: This key is used for your farming rewards address.
            By deleting this key you may lose access to any future farming rewards
            </Trans>
          </Alert>)}

          {response.wallet_balance && (<Alert severity="warning">
            <Trans>
              Warning: This key is used for a wallet that may have a non-zero balance. 
              By deleting this key you may lose access to this wallet
            </Trans>
          </Alert>)}

          <Trans>
            Warning: This key is used for your pool rewards address.
            By deleting this key you may lose access to any future pool rewards
          </Trans>
        </ConfirmDialog>,
      );

      // @ts-ignore
      if (deletePrivateKey) {
        dispatch(delete_key(fingerprint));
      }
    }
  }

  async function handleDeleteAllKeys(e: React.MouseEvent<HTMLButtonElement>) {
    const keyringCanBeModified = await handleKeyringMutator(e);

    if (keyringCanBeModified) {
      const deleteAllKeys = await openDialog((
        <ConfirmDialog
          title={<Trans>Delete all keys</Trans>}
          confirmTitle={<Trans>Delete</Trans>}
          cancelTitle={<Trans>Back</Trans>}
          confirmColor="default"
        >
          <Trans>
            Warning: This key is used for a wallet that may have a non-zero balance.
            By deleting this key you may lose access to this wallet
          </Trans>
        </ConfirmDialog>
      ));

      // @ts-ignore
      if (deleteAllKeys) {
        dispatch(delete_all_keys());
      }
    }
  }

  async function promptForKeyringMigration() {
    const beginMigration = await openDialog(
      <ConfirmDialog
        title={<Trans>Migration required</Trans>}
        confirmTitle={<Trans>Migrate</Trans>}
        cancelTitle={<Trans>Cancel</Trans>}
        confirmColor="default"
      >
        <Trans>
          Your keys have not been migrated to a new keyring. You will be unable to create new keys or delete existing keys until migration completes. Would you like to migrate your keys now?
        </Trans>
      </ConfirmDialog>,
    );

    // @ts-ignore
    if (beginMigration) {
      dispatch(skipKeyringMigration(false));
    }
  }

  async function handleKeyringMutator(e: React.MouseEvent<HTMLButtonElement>): Promise<boolean> {
    // If the keyring requires migration and the user prevoiusly skipped migration, prompt again
    if (needsKeyringMigration && skippedKeyringMigration) {
      // Disable default event handling to avoid navigation updates
      e.preventDefault();
      e.stopPropagation();

      promptForKeyringMigration();

      return false;
    }

    return true;
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
                          <Trans>Can be backed up to mnemonic seed</Trans>
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
                        <Tooltip
                          title={
                            <Trans>
                              DANGER: permanently delete private key
                            </Trans>
                          }
                        >
                          <IconButton
                            edge="end"
                            aria-label="delete"
                            onClick={(e) => handleDeletePrivateKey(e, fingerprint)}
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
            <Button
              onClick={(e) => handleKeyringMutator(e)}
              to="/wallet/add"
              variant="contained"
              color="primary"
              size="large"
              fullWidth
            >
              <Trans>Create a new private key</Trans>
            </Button>
            <Button
              onClick={(e) => handleKeyringMutator(e)}
              to="/wallet/import"
              type="submit"
              variant="outlined"
              size="large"
              fullWidth
            >
              <Trans>Import from Mnemonics (24 words)</Trans>
            </Button>
            <Button
              onClick={handleDeleteAllKeys}
              variant="outlined"
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
