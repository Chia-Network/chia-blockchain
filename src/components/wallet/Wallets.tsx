import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import {
  Box,
  Grid,
  List,
  Divider,
  ListItem,
  ListItemText,
  Typography,
} from '@material-ui/core';
import { Route, Switch, useRouteMatch, useHistory } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { Flex } from '@chia/core';
import StandardWallet from './standard/WalletStandard';
import {
  changeWalletMenu,
  standardWallet,
  CCWallet,
  RLWallet,
  DIDWallet,
} from '../../modules/walletMenu';
import { CreateWalletView } from './create/WalletCreate';
import ColouredWallet from './coloured/WalletColoured';
import RateLimitedWallet from './rateLimited/WalletRateLimited';
import DistributedWallet from './did/DIDWallet';
import type { RootState } from '../../modules/rootReducer';
import WalletType from '../../constants/WalletType';
import LayoutSidebar from '../layout/LayoutSidebar';
import config from '../../config/config';

const localTest = config.local_test;

const StyledList = styled(List)`
  width: 100%;
`;

const WalletItem = (props: any) => {
  const dispatch = useDispatch();
  const history = useHistory();
  const id = props.wallet_id;

  const wallet = useSelector(
    (state: RootState) => state.wallet_state.wallets[Number(id)],
  );
  let name = useSelector(
    (state: RootState) => state.wallet_state.wallets[Number(id)].name,
  );
  if (!name) {
    name = '';
  }

  let mainLabel = <></>;
  if (wallet.type === WalletType.STANDARD_WALLET) {
    mainLabel = <Trans>Chia Wallet</Trans>;
    name = 'Chia';
  } else if (wallet.type === WalletType.COLOURED_COIN) {
    mainLabel = <Trans>CC Wallet</Trans>;
    if (name.length > 18) {
      name = name.slice(0, 18);
      name = name.concat('...');
    }
  } else if (wallet.type === WalletType.RATE_LIMITED) {
    mainLabel = <Trans>RL Wallet</Trans>;
    if (name.length > 18) {
      name = name.slice(0, 18);
      name = name.concat('...');
    }
  } else if (wallet.type === WalletType.DISTRIBUTED_ID) {
    mainLabel = <Trans>DID Wallet</Trans>;
    if (name.length > 18) {
      name = name.slice(0, 18);
      name = name.concat('...');
    }
  }

  function presentWallet() {
    if (wallet.type === WalletType.STANDARD_WALLET) {
      dispatch(changeWalletMenu(standardWallet, wallet.id));
    } else if (wallet.type === WalletType.COLOURED_COIN) {
      dispatch(changeWalletMenu(CCWallet, wallet.id));
    } else if (wallet.type === WalletType.RATE_LIMITED) {
      dispatch(changeWalletMenu(RLWallet, wallet.id));
    } else if (wallet.type === WalletType.DISTRIBUTED_ID) {
      dispatch(changeWalletMenu(DIDWallet, wallet.id));
    }

    history.push('/dashboard/wallets');
  }

  return (
    <ListItem button onClick={presentWallet}>
      <ListItemText primary={mainLabel} secondary={name} />
    </ListItem>
  );
};

const CreateWallet = () => {
  const history = useHistory();

  function presentCreateWallet() {
    history.push('/dashboard/wallets/create');
  }

  return (
    <div>
      <Divider />
      <ListItem button onClick={presentCreateWallet}>
        <ListItemText primary={<Trans>Add Wallet</Trans>} />
      </ListItem>
      <Divider />
    </div>
  );
};

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
          <Box>{height}</Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans>connections:</Trans>
          </Box>
          <Box>{connectionCount}</Box>
        </Box>
      </div>
    </div>
  );
}

export default function Wallets() {
  const { path } = useRouteMatch();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const id = useSelector((state: RootState) => state.wallet_menu.id);
  const wallet = wallets.find((wallet) => wallet && wallet.id === id);

  return (
    <LayoutSidebar
      title={<Trans>Wallets</Trans>}
      sidebar={
        <Flex flexDirection="column" height="100%" overflow="hidden">
          <Divider />
          <StatusCard />
          <Divider />
          <Flex flexGrow={1} overflow="auto">
            <StyledList disablePadding>
              {wallets.map((wallet) => (
                <span key={wallet.id}>
                  <WalletItem wallet_id={wallet.id} key={wallet.id} />
                  <Divider />
                </span>
              ))}
            </StyledList>
          </Flex>
          {localTest && (
            <CreateWallet />
          )}
        </Flex>
      }
    >
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <Switch>
            <Route path={path} exact>
              {!!wallet && wallet.type === WalletType.STANDARD_WALLET && (
                <StandardWallet wallet_id={id} />
              )}
              {!!wallet && wallet.type === WalletType.COLOURED_COIN && (
                <ColouredWallet wallet_id={id} />
              )}
              {!!wallet && wallet.type === WalletType.RATE_LIMITED && (
                <RateLimitedWallet wallet_id={id} />
              )}
              {!!wallet && wallet.type === WalletType.DISTRIBUTED_ID && (
                // @ts-ignore
                <DistributedWallet wallet_id={id} />
              )}
            </Route>
            <Route path={`${path}/create`} exact>
              <CreateWalletView />
            </Route>
          </Switch>
        </Grid>
      </Grid>
    </LayoutSidebar>
  );
}
