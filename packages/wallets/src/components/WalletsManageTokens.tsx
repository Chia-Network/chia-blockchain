import React, { type ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { Box } from '@mui/material';
import { Button, useColorModeValue } from '@chia/core';
import styled from 'styled-components';
import { useToggle } from 'react-use';

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

  return (
    <StyledRoot>
      <StyledButtonContainer>
        <StyledMainButton onClick={toggle} fullWidth>
          <Trans>Manage token list</Trans>
        </StyledMainButton>
      </StyledButtonContainer>
      <StyledBody expanded={expanded}>
        <StyledContent >
          Tokens list
        </StyledContent>
      </StyledBody>
    </StyledRoot>
  );
}
