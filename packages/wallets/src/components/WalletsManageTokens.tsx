import React, { type ReactNode, useState } from 'react';
import { Trans } from '@lingui/macro';
import { Box, IconButton, InputBase } from '@mui/material';
import { WalletType } from '@chia/api';
import {
  Button,
  useColorModeValue,
  Spinner,
  Flex,
  Tooltip,
  useTrans,
} from '@chia/core';
import styled from 'styled-components';
import { Add, KeyboardArrowDown, KeyboardArrowUp } from '@mui/icons-material';
import { useToggle } from 'react-use';
import useWalletsList from '../hooks/useWalletsList';
import WalletTokenCard from './WalletTokenCard';
import { useNavigate } from 'react-router';
import SearchIcon from '@mui/icons-material/Search';

const Search = styled('div')(({ theme }) => ({
  position: 'relative',
  borderRadius: theme.shape.borderRadius,
  backgroundColor: theme.palette.action.selected,
  '&:hover': {
    backgroundColor: theme.palette.action.hover,
  },
  paddingLeft: theme.spacing(1),
  paddingRight: theme.spacing(1),
}));

const SearchIconWrapper = styled('div')(({ theme }) => ({
  padding: theme.spacing(0, 0),
  height: '100%',
  position: 'absolute',
  pointerEvents: 'none',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}));

const StyledInputBase = styled(InputBase)(({ theme }) => ({
  color: 'inherit',
  width: '100%',
  '& .MuiInputBase-input': {
    padding: theme.spacing(1, 1, 1, 0),
    paddingLeft: `calc(1em + ${theme.spacing(2)})`,
    transition: theme.transitions.create('width'),
    width: '100%',
  },
}));

const StyledRoot = styled(Box)`
  position: absolute;
  bottom: 0;
  left: ${({ theme }) => theme.spacing(1)};
  right: ${({ theme }) => theme.spacing(2)};
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
  border-radius: ${({ theme }) =>
    `${theme.spacing(2)} ${theme.spacing(2)} 0 0`};
  border: ${({ theme }) => `1px solid ${useColorModeValue(theme, 'border')}`};
  background-color: ${({ theme }) => theme.palette.action.hover};
  height: ${({ theme }) => theme.spacing(6)};
  pointer-events: auto;

  &:hover {
    background-color: ${({ theme }) => theme.palette.action.selected};
    border-color: ${({ theme }) => theme.palette.highlight.main};
  }
`;

const StyledBody = styled(({ expanded, ...rest }) => <Box {...rest} />)`
  pointer-events: auto;
  background-color: ${({ theme }) => theme.palette.background.default};
  transition: all 0.25s ease-out;
  overflow: hidden;
  height: ${({ expanded }) => (expanded ? '100%' : '0%')};
`;

const StyledContent = styled(Box)`
  height: 100%;
  background-color: ${({ theme }) => theme.palette.action.hover};
  padding-top: ${({ theme }) => theme.spacing(2)};
  border-left: 1px solid ${({ theme }) => useColorModeValue(theme, 'border')};
  border-right: 1px solid ${({ theme }) => useColorModeValue(theme, 'border')};
  display: flex;
  flex-direction: column;
`;

const StyledListBody = styled(Flex)`
  overflow-y: overlay;
  flex-direction: column;
  flex-grow: 1;
  margin-top: ${({ theme }) => theme.spacing(2)};
  padding-left: ${({ theme }) => theme.spacing(2)};
  padding-right: ${({ theme }) => theme.spacing(2)};
`;

const StyledButtonText = styled(Box)`
  position: relative;
`;

const StyledExpandButtonContainer = styled(Box)`
  position: absolute;
  right: ${({ theme }) => theme.spacing(-4)};
  top: ${({ theme }) => theme.spacing(0)};
`;

export type WalletsManageTokensProps = {
  children?: ReactNode;
};

export default function WalletsManageTokens(props: WalletsManageTokensProps) {
  const [expanded, toggle] = useToggle(false);
  const t = useTrans();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const { list, hide, show, isLoading } = useWalletsList(search, [
    WalletType.STANDARD_WALLET,
    WalletType.CAT,
  ]);

  function handleAddToken(event) {
    event.preventDefault();
    event.stopPropagation();

    navigate('/dashboard/wallets/create/cat/existing');
  }

  return (
    <StyledRoot>
      <StyledButtonContainer>
        <StyledMainButton
          onClick={toggle}
          data-testid="WalletsManageTokens-manage-token-list"
          fullWidth
        >
          <StyledButtonText>
            <Trans>Manage token list</Trans>
            <StyledExpandButtonContainer>
              {expanded ? <KeyboardArrowDown /> : <KeyboardArrowUp />}
            </StyledExpandButtonContainer>
          </StyledButtonText>
        </StyledMainButton>
      </StyledButtonContainer>
      <StyledBody expanded={expanded}>
        <StyledContent>
          <Flex gap={1} alignItems="center">
            <Box flexGrow={1} ml={2}>
              <Search>
                <SearchIconWrapper>
                  <SearchIcon />
                </SearchIconWrapper>
                <StyledInputBase
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t('Search...')}
                />
              </Search>
            </Box>
            <Box mr={2}>
              <Tooltip title={<Trans>Add Token</Trans>}>
                <IconButton onClick={handleAddToken}>
                  <Add />
                </IconButton>
              </Tooltip>
            </Box>
          </Flex>
          <StyledListBody>
            {isLoading ? (
              <Spinner center />
            ) : (
              <Flex gap={1} flexDirection="column" width="100%">
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
          </StyledListBody>
        </StyledContent>
      </StyledBody>
    </StyledRoot>
  );
}
