import React from 'react';
import styled from 'styled-components';
import { Route, Switch, useRouteMatch } from 'react-router';
import { useDispatch } from 'react-redux';
import { AppBar, Toolbar, IconButton, Container } from '@material-ui/core';
import {
  DarkModeToggle,
  LocaleToggle,
  Flex,
  Logo,
  ToolbarSpacing,
} from '@chia/core';
import { t } from '@lingui/macro';
import { ExitToApp as ExitToAppIcon } from '@material-ui/icons';
import { logOut } from '../../modules/message';
import { defaultLocale, locales } from '../../config/locales';
import Wallets from '../wallet/Wallets';
import BackupCreate from '../backup/BackupCreate';

const StyledRoot = styled(Flex)`
  height: 100%;
  // overflow: hidden;
`;

const StyledAppBar = styled(AppBar)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#424242' : 'white'};
  box-shadow: 0px 0px 8px rgba(0, 0, 0, 0.2);
  z-index: ${({ theme }) => theme.zIndex.drawer + 1};
`;

const StyledBody = styled(Flex)`
  min-width: 0;
`;

const StyledBrandWrapper = styled(Flex)`
  width: 100px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
`;

export default function Dashboard() {
  const { path } = useRouteMatch();
  const dispatch = useDispatch();

  function handleLogout() {
    dispatch(logOut('log_out', {}));
  }

  return (
    <StyledRoot>
      <BackupCreate />
      <StyledAppBar position="fixed" color="transparent" elevation={0}>
        <Toolbar>
          <Container maxWidth="lg">
            <Flex>
              <StyledBrandWrapper>
                <Logo height={1} />
              </StyledBrandWrapper>
              <Flex flexGrow={1} alignItems="flex-end" gap={1} />
              <LocaleToggle locales={locales} defaultLocale={defaultLocale} />
              <DarkModeToggle />
              <IconButton color="inherit" onClick={handleLogout} title={t`Log Out`}>
                <ExitToAppIcon />
              </IconButton>
            </Flex>
          </Container>
        </Toolbar>
      </StyledAppBar>
      <StyledBody flexDirection="column" flexGrow={1}>
        <ToolbarSpacing />
        <Switch>
          <Route path={`${path}/wallets/:walletId?`}>
            <Wallets />
          </Route>
        </Switch>
      </StyledBody>
    </StyledRoot>
  );
}
