import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate, useParams } from 'react-router';
import { Box, ListItemIcon, ListItemText, Typography, List, ListItem } from '@material-ui/core';
import { Button, Flex, Loading, useTrans } from '@chia/core';
import { useGetWalletsQuery } from '@chia/api-react';
import { WalletType, type Wallet } from '@chia/api';
import WalletName from '../constants/WalletName';
import WalletIcon from './WalletIcon';
import WalletBadge from './WalletBadge';
import styled from 'styled-components';

const StyledRoot = styled(Box)`
  padding-left: ${({ theme }) => theme.spacing(4)}px;
  min-width: 330px;
`;

const StyledListItem = styled(ListItem)`
  border-radius: ${({ theme }) => theme.spacing(1)}px;
  border: ${({ selected }) => `1px solid ${selected ? '#00C853' : '#E0E0E0'}`};
  margin-bottom: ${({ theme }) => theme.spacing(1)}px;
  background-color: ${({ selected }) => selected ? 'white' : 'white'};
`;

function getPrimaryTitle(wallet: Wallet): string {
  switch (wallet.type) {
    case WalletType.STANDARD_WALLET:
      return 'Chia';
    default:
      return wallet.name;
  }
}


export default function WalletsSidebar() {
  const navigate = useNavigate();
  const trans = useTrans();
  const { walletId } = useParams(); 
  const { data: wallets, isLoading } = useGetWalletsQuery();

  function handleSelectWallet(walletId: number) {
    navigate(`/dashboard/wallets/${walletId}`);
  }

  function handleAddToken() {
    navigate('/dashboard/wallets/create/simple');
  }

  const items = useMemo(() => {
    if (isLoading) {
      return [];
    }

    return wallets
      .filter(wallet => ![WalletType.POOLING_WALLET].includes(wallet.type))
      .map((wallet) => {
        const primaryTitle = getPrimaryTitle(wallet);
        const secondaryTitle = trans(WalletName[wallet.type]);
        const hasSameTitle = primaryTitle.toLowerCase() === secondaryTitle.toLowerCase();

        function handleSelect() {
          handleSelectWallet(wallet.id);
        }

        return (
          <StyledListItem key={wallet.id} selected={wallet.id === Number(walletId)} onClick={handleSelect}>
            <ListItemIcon>
              <WalletIcon wallet={wallet} />
            </ListItemIcon>
            <ListItemText
              primary={(
                <Flex gap={1} alignItems="center">
                  <Typography>{primaryTitle}</Typography>
                  <WalletBadge wallet={wallet} fontSize="small" tooltip />
                </Flex>
              )}
              secondary={!hasSameTitle ? secondaryTitle: undefined}
              secondaryTypographyProps={{
                variant: 'caption',
              }}
            />
          </StyledListItem>
        );
      });
  }, [wallets, walletId, isLoading]);

  return (
    <StyledRoot>
      <Flex gap={2} flexDirection="column">
        <Typography variant="h5">
          <Trans>Tokens</Trans>
          &nbsp;
          <Button
            color="primary"
            onClick={handleAddToken}
          >
            <Trans>+</Trans>
          </Button>
        </Typography>
        <List>
          {items}
        </List>
      </Flex>
    </StyledRoot>
  );
}
