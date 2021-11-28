import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { ConfirmDialog, useOpenDialog, LoadingOverlay, useShowError } from '@chia/core';
import { Alert } from '@material-ui/lab';
import {
  Tooltip,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
} from '@material-ui/core';
import { useNavigate } from 'react-router';
import {
  Delete as DeleteIcon,
  Visibility as VisibilityIcon,
} from '@material-ui/icons';
import {
  useCheckDeleteKeyMutation,
  useDeleteKeyMutation,
  useLogInAndSkipImportMutation,
} from '@chia/api-react';
import SelectKeyDetailDialog from './SelectKeyDetailDialog';

const StyledFingerprintListItem = styled(ListItem)`
  padding-right: ${({ theme }) => `${theme.spacing(11)}px`};
`;

type Props = {
  fingerprint: number;
};

export default function SelectKeyItem(props: Props) {
  const { fingerprint } = props;
  const navigate = useNavigate();
  const openDialog = useOpenDialog();
  const [deleteKey] = useDeleteKeyMutation();
  const [checkDeleteKey] = useCheckDeleteKeyMutation();
  const [logIn] = useLogInAndSkipImportMutation();
  const [loading, setLoading] = useState<boolean>(false);
  const showError = useShowError();

  async function handleLogin() {
    try {
      setLoading(true);
      await logIn({
        fingerprint,
      }).unwrap();
  
      navigate('/dashboard');
    } catch (error) {
      showError(error)
    } finally {
      setLoading(false);
    }
  }

  function handleShowKey(event) {
    event.stopPropagation();

    openDialog((
      <SelectKeyDetailDialog fingerprint={fingerprint} />
    ));
  }

  async function handleDeletePrivateKey(event) {
    event.stopPropagation();

    const { 
      data: { 
        usedForFarmerRewards,
        usedForPoolRewards,
        walletBalance,
    } } = await checkDeleteKey({
      fingerprint,
    });

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
    <LoadingOverlay loading={loading}>
      <StyledFingerprintListItem
        onClick={handleLogin}
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
            >
              <DeleteIcon />
            </IconButton>
          </Tooltip>
        </ListItemSecondaryAction>
      </StyledFingerprintListItem>
    </LoadingOverlay>
  );
}
