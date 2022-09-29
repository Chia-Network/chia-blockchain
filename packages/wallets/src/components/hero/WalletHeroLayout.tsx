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
} from '@mui/material';
import styled from 'styled-components';
import {
  ChevronRight as ChevronRightIcon,
  EnergySavingsLeaf as EcoIcon,
} from '@mui/icons-material';
import { useSelector } from 'react-redux';
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
import useTrans from '../../../hooks/useTrans';
import WalletsList from '../WalletsList';
import WalletHeroWallets from './WalletHeroWallets';
import WalletHeroAdd from './WalletHeroAdd';

const StyledListItem = styled(ListItem)`
  min-width: 300px;
`;

const { multipleWallets, asteroid } = config;

type Props = {
  title: ReactNode;
  children: ReactNode;
};

export default function Wallets(props: Props) {
  const { title, children } = props;
  const trans = useTrans();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const loading = !wallets;

  return (
    <LayoutHero>
      <Container maxWidth="xs">
        <Flex flexDirection="column" alignItems="center" gap={3}>
          <Logo width={130} />
          <Back to="/">
            <Typography variant="h5" component="h1">
              {title}
            </Typography>
          </Back>
          <Flex
            flexDirection="column"
            gap={3}
            alignItems="stretch"
            alignSelf="stretch"
          >
            {children}
          </Flex>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
