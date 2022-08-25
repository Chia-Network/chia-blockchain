import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Trans } from '@lingui/macro';
import { Grid } from '@mui/material';
import { Restore as RestoreIcon, Add as AddIcon } from '@mui/icons-material';
import { Back, Flex } from '@chia/core';
import WalletCreateCard from '../create/WalletCreateCard';

export default function WalletCATSelect() {
  const navigate = useNavigate();

  function handleCreateNew() {
    navigate(`create`);
  }

  function handleCreateExisting() {
    navigate(`existing`);
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexGrow={1}>
        <Back variant="h5" to="/dashboard/wallets/create">
          <Trans>Chia Asset Token</Trans>
        </Back>
      </Flex>
      <Grid spacing={3} alignItems="stretch" container>
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            onSelect={handleCreateNew}
            title={<Trans>Create New Wallet</Trans>}
            icon={<AddIcon fontSize="large" color="primary" />}
          />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            onSelect={handleCreateExisting}
            title={<Trans>Recovery Wallet</Trans>}
            icon={<RestoreIcon fontSize="large" color="primary" />}
          />
        </Grid>
      </Grid>
    </Flex>
  );
}
