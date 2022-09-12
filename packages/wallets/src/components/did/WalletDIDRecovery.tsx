import React, { useState } from 'react';
import { useNavigate } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { AlertDialog, Back, ButtonLoading, Card, Flex, Dropzone, useOpenDialog } from '@chia/core';
import { Trans } from '@lingui/macro';
import {
  Typography,
  Button,
  Box,
} from '@mui/material';
import { Backup as BackupIcon } from '@mui/icons-material';
import type { RootState } from '../../../modules/rootReducer';
import { recover_did_action } from '../../../modules/message';
import SyncingStatus from '../../../constants/SyncingStatus';
import getWalletSyncingStatus from '../../../util/getWalletSyncingStatus';

export default function WalletDIDRecovery() {
  const openDialog = useOpenDialog();
  const navigate = useNavigate();
  const [loading, setLoading] = useState<boolean>(false);
  const dispatch = useDispatch();
  const [file, setFile] = useState();

  const walletState = useSelector((state: RootState) => state.wallet_state);
  const syncingStatus = getWalletSyncingStatus(walletState);

  const isSynced = syncingStatus === SyncingStatus.SYNCED;

  function handleDrop(acceptedFiles) {
    if (acceptedFiles.length > 1) {
      openDialog(
        <AlertDialog>
          <Trans>Only one backup file is allowed.</Trans>
        </AlertDialog>
      );
      return;
    }

    const [first] = acceptedFiles;
    setFile(first);
  }

  function handleRemoveFile(event) {
    event.preventDefault();
    event.stopPropagation();

    setFile(undefined);
  }

  async function handleSubmit() {
    if (!file) {
      await openDialog((
        <AlertDialog>
          <Trans>Please select backup file first</Trans>
        </AlertDialog>
      ));
      return;
    }

    if (!isSynced) {
      await openDialog((
        <AlertDialog>
          <Trans>Please wait for wallet synchronization</Trans>
        </AlertDialog>
      ));
      return;
    }

    try {
      setLoading(true);
      const response = await dispatch(recover_did_action(file.path));
      if (response && response.data && response.data.success === true) {
        navigate(`/dashboard/wallets/${response.data.wallet_id}`);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Back variant="h5">
        <Trans>Recover Distributed Identity Wallet</Trans>
      </Back>
      <Card>
        <Dropzone onDrop={handleDrop}>
          {file ? (
            <Flex flexDirection="column" gap={2} flexBasis={0} width="100%">
              <Typography variant="subtitle1" align="center">
                <Trans>Selected recovery file:</Trans>
              </Typography>
              <Typography variant="body2" align="center" noWrap>
                {file.name}
              </Typography>
              <Flex justifyContent="center">
                <Button
                  onClick={handleRemoveFile}
                  variant="contained"
                  color="danger"
                >
                  <Trans>Delete</Trans>
                </Button>
              </Flex>
            </Flex>
          ): (
            <Flex flexDirection="column" gap={2} alignItems="center">
              <BackupIcon fontSize="large" />
              <Typography variant="body2" align="center">
                <Trans>
                  Drag and drop your recovery backup file
                </Trans>
              </Typography>
            </Flex>
          )}
        </Dropzone>
      </Card>
      <Box>
        <ButtonLoading
          onClick={handleSubmit}
          variant="contained"
          color="primary"
          loading={loading}
        >
          <Trans>Recover</Trans>
        </ButtonLoading>
      </Box>
    </Flex>
  );
}
