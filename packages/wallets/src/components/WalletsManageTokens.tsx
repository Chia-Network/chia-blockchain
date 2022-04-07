import React, { type ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { Box, Typography, Switch, IconButton } from '@mui/material';
import { Button, useColorModeValue, Spinner, CardListItem, Flex } from '@chia/core';
import styled from 'styled-components';
import { Add } from '@mui/icons-material';
import { useToggle } from 'react-use';
import useWalletsList from '../hooks/useWalletsList';
import WalletTokenCard from './WalletTokenCard';
import { useNavigate } from 'react-router';

const StyledRoot = styled(Box)`
  position: absolute;
  bottom: 0;
  left: ${({ theme }) => theme.spacing(1)};
  right: ${({ theme }) => theme.spacing(1)};
  top: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  z-index: 1;
  pointer-events: none;
`;

const StyledButtonContainer = styled(Box)`
  background-color: ${({ theme }) => theme.palette.background.default};
`;

const StyledMainButton = styled(Button)`
  border-radius: ${({ theme }) => `${theme.spacing(2)} ${theme.spacing(2)} 0 0`};
  border: ${({ theme }) => `1px solid ${useColorModeValue(theme, 'border')}`};
  background-color: ${({ theme }) => theme.palette.action.hover};
  padding: ${({ theme }) => theme.spacing(3)};
  pointer-events: auto;

  &:hover {
    background-color: ${({ theme }) => theme.palette.action.hover};
    border-color: ${({ theme }) => theme.palette.highlight.main};
  }
`;

const StyledBody = styled(Box)`
  pointer-events: auto;
  background-color: ${({ theme }) => theme.palette.background.default};
  transition: all 0.25s ease-out;
  overflow: hidden;
  height: ${({ expanded }) => expanded ? '100%' : '0%'};
`;

const StyledContent = styled(Box)`
  overflow: auto;
  height: 100%;
  background-color: ${({ theme }) => theme.palette.action.hover};
  padding-left: ${({ theme }) => theme.spacing(3)};
  padding-right: ${({ theme }) => theme.spacing(3)};
  padding-top: ${({ theme }) => theme.spacing(2)};
  border-left: 1px solid ${({ theme }) => useColorModeValue(theme, 'border')};
  border-right: 1px solid ${({ theme }) => useColorModeValue(theme, 'border')};
`;

export type WalletsManageTokensProps = {
  children?: ReactNode;
};

export default function WalletsManageTokens(props: WalletsManageTokensProps) {
  const [expanded, toggle] = useToggle(false);
  const navigate = useNavigate();
  const { list, hide, show, isLoading } = useWalletsList();

  function handleAddToken(event) {
    event.preventDefault();
    event.stopPropagation();

    navigate('/dashboard/wallets/create/cat/existing');
  }

  return (
    <StyledRoot>
      <StyledButtonContainer>
        <StyledMainButton onClick={toggle} fullWidth>
          <Trans>Manage token list</Trans>
          &nbsp;
          <IconButton onClick={handleAddToken}>
            <Add />
          </IconButton>
        </StyledMainButton>
      </StyledButtonContainer>
      <StyledBody expanded={expanded}>
        <StyledContent >
          {isLoading ? (
            <Spinner center />
          ) : (
            <Flex gap={1} flexDirection="column">
              {list?.map((list) => (
                <WalletTokenCard
                  item={list}
                  key={list.id}
                  onHide={hide}
                  onShow={show}
                />
              ))}
            </Flex>
          )}
        </StyledContent>
      </StyledBody>
    </StyledRoot>
  );
}
