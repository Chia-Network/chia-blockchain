import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Button,
  Card,
  List,
  ListItem,
  ListItemText,
} from '@material-ui/core';
import styled from 'styled-components';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useSelector } from 'react-redux';
import { Flex, Loading, Logo } from '@chia/core';
import type { RootState } from '../../../modules/rootReducer';
import WalletName from '../../../constants/WalletName';
import config from '../../../config/config';
import { useNavigate } from 'react-router-dom';
import useTrans from '../../../hooks/useTrans';
import WalletHeroLayout from './WalletHeroLayout';

const StyledListItem = styled(ListItem)`
  min-width: 300px;
`;

const { asteroid } = config;

export default function Wallets() {
  const navigate = useNavigate();
  const trans = useTrans();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  function handleChange(_, newValue) {
    if (asteroid && newValue === 'create') {
      navigate('/dashboard/wallets/create/simple');
      return;
    }

    navigate(`/dashboard/wallets/${newValue}`);
  }

  function handleAddToken() {
    navigate(`/wallets/add`);
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
