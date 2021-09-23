import React, { useEffect } from 'react';
import { Trans } from '@lingui/macro';
import {
  Box,
  Typography,
  Tabs,
  Tab,
  Container,
} from '@material-ui/core';
import styled from 'styled-components';
// import { useRouteMatch, useHistory } from 'react-router';
import { /*useDispatch, */ useSelector } from 'react-redux';
import { FormatLargeNumber } from '@chia/core';
import StandardWallet from './standard/WalletStandard';
import { CreateWalletView } from './create/WalletCreate';
import ColouredWallet from './coloured/WalletColoured';
import RateLimitedWallet from './rateLimited/WalletRateLimited';
import DistributedWallet from './did/WalletDID';
import type { RootState } from '../../modules/rootReducer';
import WalletType from '../../constants/WalletType';
import LayoutMain from '../layout/LayoutMain';
import config from '../../config/config';
import { Switch, Route, useHistory, useRouteMatch, useParams } from 'react-router-dom';

const { multipleWallets } = config;

const StyledTabs = styled(Tabs)`
  flex-grow: 1;
  box-shadow: inset 0 -1px 0 ${({ theme }) => theme.palette.type === 'dark' ? '#222222' : '#DBDBDB'};
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
  const history = useHistory();
  const { walletId } = useParams();
  const { path } = useRouteMatch();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const loading = !wallets;

  function handleChange(_, newValue) {
    history.push(`/dashboard/wallets/${newValue}`);
  }

  // redirect to default "standard wallet" when no wallet was selected
  useEffect(() => {
    if (!walletId && wallets) {
      history.push('/dashboard/wallets/1');
    }
  }, [wallets, walletId]);

  return (
    <LayoutMain
      loading={loading}
      loadingTitle={<Trans>Loading list of wallets</Trans>}
      title={<Trans>Wallets</Trans>}
      bodyHeader={multipleWallets ? (
        <Container maxWidth="lg">
          <StyledTabs
            value={walletId || '1'}
            onChange={handleChange}
            indicatorColor="primary"
            textColor="primary"
            scrollButtons="auto"
            variant="scrollable"
          >
            {wallets?.map((wallet) => (
              <Tab label={wallet.name} value={String(wallet.id)} key={wallet.id} />
            ))}
            <Tab value="create" label={<Trans>+ Add Wallet</Trans>} />
          </StyledTabs>
        </Container>
      ) : undefined}
    >
      {multipleWallets ? (
        <Switch>
          {wallets?.map((wallet) => (
            <Route path={`${path}/${wallet.id}`} key={wallet.id}>
              {wallet.type === WalletType.STANDARD_WALLET && (
                <StandardWallet wallet_id={wallet.id} />
              )}

              {wallet.type === WalletType.COLOURED_COIN && (
                <ColouredWallet wallet_id={wallet.id} />
              )}

              {wallet.type === WalletType.RATE_LIMITED && (
                <RateLimitedWallet wallet_id={wallet.id} />
              )}

              {wallet.type === WalletType.DISTRIBUTED_ID && (
                <DistributedWallet walletId={wallet.id} />
              )}
            </Route>
          ))}
          <Route path={`/dashboard/wallets/create`}>
            <CreateWalletView />
          </Route>
        </Switch>
      ) : (
        <StandardWallet wallet_id={1} showTitle />
      )}
    </LayoutMain>
  );
}
