import React, { useState } from 'react';
import { t, Trans } from '@lingui/macro';
import {
  Box,
  Typography,
  Tabs,
  Tab,
} from '@material-ui/core';
import styled from 'styled-components';
// import { useRouteMatch, useHistory } from 'react-router';
import { /*useDispatch, */ useSelector } from 'react-redux';
import { Button, Flex, FormatLargeNumber } from '@chia/core';
import StandardWallet from './standard/WalletStandard';
import { CreateWalletView } from './create/WalletCreate';
import ColouredWallet from './coloured/WalletColoured';
import RateLimitedWallet from './rateLimited/WalletRateLimited';
import DistributedWallet from './did/DIDWallet';
import type { RootState } from '../../modules/rootReducer';
import WalletType from '../../constants/WalletType';
import LayoutMain from '../layout/LayoutMain';
import config from '../../config/config';

const { multipleWallets } = config;

const RightButton = styled(Button)`
  margin-left: auto;
`;

const StyledTabs = styled(Tabs)`
  flex-grow: 1;
  margin-top: -0.5rem;
`;

export function StatusCard() {
  const syncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );
  const synced = useSelector(
    (state: RootState) => state.wallet_state.status.synced,
  );

  const height = useSelector(
    (state: RootState) => state.wallet_state.status.height,
  );
  const connectionCount = useSelector(
    (state: RootState) => state.wallet_state.status.connection_count,
  );

  return (
    <div style={{ margin: 16 }}>
      <Typography variant="subtitle1">
        <Trans>Status</Trans>
      </Typography>
      <div style={{ marginLeft: 8 }}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans>status:</Trans>
          </Box>
          <Box>
            {(() => {
              if (syncing) return <Trans>syncing</Trans>;
              if (synced) return <Trans>synced</Trans>;
              if (!synced) return <Trans>not synced</Trans>;
            })()}
          </Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans>height:</Trans>
          </Box>
          <Box>
            <FormatLargeNumber value={height} />
          </Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans>connections:</Trans>
          </Box>
          <Box>
            <FormatLargeNumber value={connectionCount} />
          </Box>
        </Box>
      </div>
    </div>
  );
}

function TabPanel(props) {
  const { children, value, selected } = props;

  if (value === selected) {
    return children;
  }

  return null;
}

export default function Wallets() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const id = useSelector((state: RootState) => state.wallet_menu.id);
  const [selected, setSelected] = useState<string | number>(id);
  const loading = !wallets;

  function handleChange(event, newValue) {
    setSelected(newValue);
  }

  return (
    <LayoutMain
      loading={loading}
      loadingTitle={<Trans>Loading list of wallets</Trans>}
      title={<Trans>Wallets</Trans>}
    >
      {multipleWallets ? (
        <Box>
          <Flex alignItems="center" gap={1} >
            <Flex flexGrow={1}>
              <StyledTabs value={selected} onChange={handleChange} indicatorColor="primary" textColor="primary">
                {wallets?.map((wallet) => (
                  <Tab label={wallet.name} value={wallet.id} key={wallet.id} />
                ))}
                <Tab value="add" label={<Trans>+ Add Wallet</Trans>} />
              </StyledTabs>
            </Flex>
          </Flex>

          {wallets?.map((wallet) => (
            <TabPanel selected={selected} value={wallet.id}>
              {wallet.type === WalletType.STANDARD_WALLET && (
                <StandardWallet wallet_id={id} />
              )}

              {wallet.type === WalletType.COLOURED_COIN && (
                <ColouredWallet wallet_id={id} />
              )}

              {wallet.type === WalletType.RATE_LIMITED && (
                <RateLimitedWallet wallet_id={id} />
              )}

              {wallet.type === WalletType.DISTRIBUTED_ID && (
                <DistributedWallet wallet_id={id} />
              )}
            </TabPanel>
          ))}
          <TabPanel selected={selected} value="add">
            <CreateWalletView />
          </TabPanel>
        </Box>
      ) : (
        <StandardWallet wallet_id={1} showTitle />
      )}
    </LayoutMain>
  );
}
