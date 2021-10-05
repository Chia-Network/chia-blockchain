import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Grid, Typography,
} from '@material-ui/core';
import { useSelector } from 'react-redux';
import { Flex, Loading } from '@chia/core';
import { useHistory } from 'react-router';
import { Eco as HomeWorkIcon, Add as AddIcon } from '@material-ui/icons';
import type { RootState } from '../../modules/rootReducer';
import Wallet from '../../types/Wallet';
import WalletCreateCard from './create/WalletCreateCard';
import WalletName from '../../constants/WalletName';
import useTrans from '../../hooks/useTrans';

export default function WalletsList() {
  const history = useHistory();
  const trans = useTrans();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  function handleSelectWallet(wallet: Wallet) {
    console.log('wallet', wallet);
    history.push(`/dashboard/wallets/${wallet.id}`);
  }

  function handleAddToken() {
    history.push(`/dashboard/wallets/create/simple`);
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexGrow={1}>
        <Typography variant="h5">
          <Trans>Select Wallet</Trans>
        </Typography>
      </Flex>
      <Grid spacing={3} alignItems="stretch" container>
        {!wallets && (
          <Loading center />
        )}
        {wallets && (
          <>
            {wallets.map(wallet => (
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
