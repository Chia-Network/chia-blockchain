import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import {
  Alert,
  Tooltip,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
} from '@mui/material';
import {
  Delete as DeleteIcon,
  Visibility as VisibilityIcon,
} from '@mui/icons-material';
import {
  useCheckDeleteKeyMutation,
  useDeleteKeyMutation,
  useGetKeyringStatusQuery,
} from '@chia/api-react';
import SelectKeyDetailDialog from './SelectKeyDetailDialog';
import ConfirmDialog from '../../components/ConfirmDialog';
import LoadingOverlay from '../../components/LoadingOverlay';
import useOpenDialog from '../../hooks/useOpenDialog';
import useSkipMigration from '../../hooks/useSkipMigration';
import useKeyringMigrationPrompt from '../../hooks/useKeyringMigrationPrompt';

const StyledFingerprintListItem = styled(ListItem)`
  padding-right: ${({ theme }) => `${theme.spacing(11)}`};
`;

type Props = {
  fingerprint: number;
  disabled?: boolean;
  loading?: boolean;
  onSelect: (fingerprint: number) => void;
};

export default function SelectKeyItem(props: Props) {
  const { fingerprint, onSelect, disabled, loading } = props;
  const { data: keyringState, isLoading: isLoadingKeyringStatus } = useGetKeyringStatusQuery();
  const openDialog = useOpenDialog();
  const [deleteKey] = useDeleteKeyMutation();
  const [checkDeleteKey] = useCheckDeleteKeyMutation();
  const [skippedMigration] = useSkipMigration();
  const [promptForKeyringMigration] = useKeyringMigrationPrompt();

  async function handleLogin() {
    onSelect(fingerprint);
  }

  function handleShowKey(event) {
    event.stopPropagation();

    openDialog((
      <SelectKeyDetailDialog fingerprint={fingerprint} />
    ));
  }

  async function handleDeletePrivateKey(event) {
    const canModifyKeyring = await handleKeyringMutator();

    if (!canModifyKeyring) {
      return;
    }

    event.stopPropagation();

    const {
      data: {
        usedForFarmerRewards,
        usedForPoolRewards,
        walletBalance,
    } } = await checkDeleteKey({
      fingerprint,
    });

    async function handleKeyringMutator(): Promise<boolean> {
      // If the keyring requires migration and the user previously skipped migration, prompt again
      if (isLoadingKeyringStatus || (keyringState?.needsMigration && skippedMigration)) {
        await promptForKeyringMigration();

        return false;
      }

      return true;
    }

    await openDialog(
      <ConfirmDialog
        title={<Trans>Delete key {fingerprint}</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        cancelTitle={<Trans>Back</Trans>}
        confirmColor="danger"
        onConfirm={() => deleteKey({ fingerprint }).unwrap()}
      >
        {usedForFarmerRewards && (
          <Alert severity="warning">
            <Trans>
              Warning: This key is used for your farming rewards address.
              By deleting this key you may lose access to any future farming rewards
              </Trans>
          </Alert>
        )}

        {usedForPoolRewards && (
          <Alert severity="warning">
            <Trans>
              Warning: This key is used for your pool rewards address.
              By deleting this key you may lose access to any future pool rewards
            </Trans>
          </Alert>
        )}

        {walletBalance && (
          <Alert severity="warning">
            <Trans>
              Warning: This key is used for a wallet that may have a non-zero balance.
              By deleting this key you may lose access to this wallet
            </Trans>
          </Alert>
        )}

        <Trans>
          Deleting the key will permanently remove the key from your computer,
          make sure you have backups. Are you sure you want to continue?
        </Trans>
      </ConfirmDialog>,
    );
  }

  return (
    <LoadingOverlay loading={loading} disabled={disabled}>
      <StyledFingerprintListItem
        onClick={handleLogin}
        data-testid={`SelectKeyItem-fingerprint-${fingerprint}`}
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
              onClick={handleShowKey}
              data-testid={`SelectKeyItem-detail-${fingerprint}`}
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
              onClick={handleDeletePrivateKey}
              data-testid={`SelectKeyItem-delete-${fingerprint}`}
            >
              <DeleteIcon />
            </IconButton>
          </Tooltip>
        </ListItemSecondaryAction>
      </StyledFingerprintListItem>
    </LoadingOverlay>
  );
}
