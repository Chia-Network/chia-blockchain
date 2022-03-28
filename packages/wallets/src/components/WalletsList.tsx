import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Grid, Typography,
} from '@mui/material';
import { useGetWalletsQuery } from '@chia/api-react';
import { Flex, Loading } from '@chia/core';
import { useNavigate } from 'react-router';
import { Eco as HomeWorkIcon, Add as AddIcon } from '@mui/icons-material';
import Wallet from '../../types/Wallet';
import WalletCreateCard from './create/WalletCreateCard';
import WalletName from '../../constants/WalletName';
import useTrans from '../../hooks/useTrans';

export default function WalletsList() {
  const navigate = useNavigate();
  const trans = useTrans();
  const { data: wallets, isLoading } = useGetWalletsQuery();

  function handleSelectWallet(wallet: Wallet) {
    navigate(`/dashboard/wallets/${wallet.id}`);
  }

  function handleAddToken() {
    navigate(`/dashboard/wallets/create/simple`);
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexGrow={1}>
        <Typography variant="h5">
          <Trans>Select Wallet</Trans>
        </Typography>
      </Flex>
      <Grid spacing={3} alignItems="stretch" container>
        {isLoading ? (
          <Loading center />
        ) : (
          <>
            {wallets.map((wallet) => (
              <Grid key={wallet.id} xs={12} sm={6} md={4} item>
                <WalletCreateCard
                  onSelect={() => handleSelectWallet(wallet)}
                  title={trans(WalletName[wallet.type])}
                  icon={<HomeWorkIcon fontSize="large" color="primary" />}
                />
              </Grid>
            ))}
          </>
        )}
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            onSelect={handleAddToken}
            title={<Trans>Add Token</Trans>}
            icon={<AddIcon fontSize="large" color="primary" />}
          />
        </Grid>
      </Grid>
    </Flex>
  );
}
