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
import WalletHeroWallets from './WalletHeroWallets';
import WalletHeroAdd from './WalletHeroAdd';

export default function Wallets() {
  const { path } = useRouteMatch();

  return (
    <Switch>
      <Route path="/wallets" exact>
        <WalletHeroWallets />
      </Route>
      <Route path="/wallets/add" exact>
        <WalletHeroAdd />
      </Route>
    </Switch>
  );
}
