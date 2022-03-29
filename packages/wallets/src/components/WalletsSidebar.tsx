import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate, useParams } from 'react-router';
import { Card, CardContent, Box, IconButton, ListItemIcon, ListItemText, Typography, List, ListItem, CardActionArea } from '@mui/material';
import { Add } from '@mui/icons-material';
import { Button, Flex, Loading, useTrans, useColorModeValue } from '@chia/core';
import { useGetWalletsQuery } from '@chia/api-react';
import { WalletType, type Wallet } from '@chia/api';
import styled from 'styled-components';
import WalletName from '../constants/WalletName';
import WalletIcon from './WalletIcon';
import WalletBadge from './WalletBadge';
import getWalletPrimaryTitle from '../utils/getWalletPrimaryTitle';
import WalletsManageTokens from './WalletsManageTokens';

const StyledRoot = styled(Box)`
  min-width: 330px;
  height: 100%;
  display: flex;
  padding-top: ${({ theme }) => `${theme.spacing(3)}`};
`;

const StyledCard = styled(Card)`
  width: 100%;
  border-radius: ${({ theme }) => theme.spacing(1)};
  border: ${({ theme }) => `1px solid ${useColorModeValue(theme, 'border')}`};
  margin-bottom: ${({ theme }) => theme.spacing(1)};

  &:hover {
    border-color: ${({ theme }) => theme.palette.highlight.main};
  }
`;

const StyledContent = styled(Box)`
  padding-left: ${({ theme }) => theme.spacing(4)};
  padding-right: ${({ theme }) => theme.spacing(4)};
  min-height: ${({ theme }) => theme.spacing(7)};
`;

const StyledBody = styled(Box)`
  flex-grow: 1;
  position: relative;
`;

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
        const primaryTitle = getWalletPrimaryTitle(wallet);

        function handleSelect() {
          handleSelectWallet(wallet.id);
        }

        return (
          <StyledCard variant="outlined" key={wallet.id} selected={wallet.id === Number(walletId)}>
            <CardActionArea onClick={handleSelect}>
              <CardContent>
                <Flex flexDirection="column">
                  <Typography>{primaryTitle}</Typography>
                  <WalletIcon wallet={wallet} color="grey" variant="caption" />
                </Flex>
              </CardContent>
            </CardActionArea>
          </StyledCard>
        );
      });
  }, [wallets, walletId, isLoading]);

  return (
    <StyledRoot>
      <Flex gap={1} flexDirection="column" width="100%">
        <StyledContent>
          <Typography variant="h5">
            <Trans>Tokens</Trans>
            &nbsp;
            <IconButton onClick={handleAddToken}>
              <Add />
            </IconButton>
          </Typography>
        </StyledContent>
        <StyledBody>
          <StyledContent>
            <Flex gap={1} flexDirection="column">
              {items}
            </Flex>
          </StyledContent>
          <WalletsManageTokens />
        </StyledBody>
      </Flex>
    </StyledRoot>
  );
}
