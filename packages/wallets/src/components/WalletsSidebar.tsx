import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate, useParams } from 'react-router';
import { Box, ListItemIcon, ListItemText, Typography, List, ListItem } from '@mui/material';
import { Button, Flex, Loading, useTrans, useColorModeValue } from '@chia/core';
import { useGetWalletsQuery } from '@chia/api-react';
import { WalletType, type Wallet } from '@chia/api';
import styled from 'styled-components';
import WalletName from '../constants/WalletName';
import WalletIcon from './WalletIcon';
import WalletBadge from './WalletBadge';
import WalletsManageTokens from './WalletsManageTokens';

const StyledRoot = styled(Box)`
  min-width: 330px;
  height: 100%;
  display: flex;
  padding-top: ${({ theme }) => `${theme.spacing(3)}`};
`;

const StyledListItem = styled(ListItem)`
  border-radius: ${({ theme }) => theme.spacing(1)};
  border: ${({ theme }) => `1px solid ${useColorModeValue(theme, 'border')}`};
  margin-bottom: ${({ theme }) => theme.spacing(1)};
  background-color: ${({ selected, theme }) => selected ? theme.palette.action.selected : theme.palette.action.hover};

  &:hover {
    border-color: ${({ theme }) => theme.palette.highlight.main};
  }
`;

const StyledContent = styled(Box)`
  padding-left: ${({ theme }) => theme.spacing(4)};
  padding-right: ${({ theme }) => theme.spacing(4)};
`;

const StyledBody = styled(Box)`
  flex-grow: 1;
  position: relative;
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
      <Flex gap={2} flexDirection="column" width="100%">
        <StyledContent>
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
        </StyledContent>
        <StyledBody>
          <StyledContent>
            <List>
              {items}
            </List>
          </StyledContent>
          <WalletsManageTokens />
        </StyledBody>
      </Flex>
    </StyledRoot>
  );
}
