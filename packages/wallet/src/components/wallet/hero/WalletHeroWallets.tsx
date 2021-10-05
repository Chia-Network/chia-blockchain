import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Box,
  Button,
  Container,
  Typography,
  Card,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
} from '@material-ui/core';
import styled from 'styled-components';
import { ChevronRight as ChevronRightIcon, Eco as EcoIcon } from '@material-ui/icons';
import {  useSelector } from 'react-redux';
import { Back, Flex, FormatLargeNumber, Loading, Logo } from '@chia/core';
import StandardWallet from '../standard/WalletStandard';
import { CreateWalletView } from '../create/WalletCreate';
import WalletCAT from '../cat/WalletCAT';
import RateLimitedWallet from '../rateLimited/WalletRateLimited';
import DistributedWallet from '../did/WalletDID';
import type { RootState } from '../../../modules/rootReducer';
import WalletType from '../../../constants/WalletType';
import WalletName from '../../../constants/WalletName';
import LayoutMain from '../../layout/LayoutMain';
import LayoutHero from '../../layout/LayoutHero';
import config from '../../../config/config';
import { Switch, Route, useHistory, useRouteMatch, useParams } from 'react-router-dom';
import useTrans from '../../../hooks/useTrans';
import WalletsList from '../WalletsList';
import WalletHeroLayout from './WalletHeroLayout';

const StyledListItem = styled(ListItem)`
  min-width: 300px;
`;

const { multipleWallets, asteroid } = config;

export default function Wallets() {
  const history = useHistory();
  const { walletId } = useParams();
  const { path, ...rest } = useRouteMatch();
  const trans = useTrans();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const loading = !wallets;

  function handleChange(_, newValue) {
    if (asteroid && newValue === 'create') {
      history.push('/dashboard/wallets/create/simple');
      return;
    }

    history.push(`/dashboard/wallets/${newValue}`);
  }


  function handleAddToken() {
    history.push(`/wallets/add`);
  }

  return (
    <WalletHeroLayout
      title={<Trans>Select Wallet</Trans>}
    >
      {!wallets ? (
        <Loading center />
      ) : (
        <Card>
          <List>
            {wallets.map((wallet: Wallet) => (
              <StyledListItem
                onClick={() => handleChange(null, wallet.id)}
                key={wallet.id}
                button
              >
                <Flex flexGrow={1} alignItems="center">
                  <Flex flexGrow={1} gap={3} alignItems="center">
                    <Logo width={32} />
                  
                    <ListItemText
                      primary={trans(WalletName[wallet.type])}
                      secondary={wallet.name}
                    />
                  </Flex>

                  <ChevronRightIcon />
                </Flex>
              </StyledListItem>
            ))}
          </List>
        </Card>
      )}
      <Button
        onClick={handleAddToken}
        variant="outlined"
        size="large"
        fullWidth
      >
        <Trans>Add Token</Trans>
      </Button>
    </WalletHeroLayout>
  );
}
