import React from 'react';
import styled from 'styled-components';
import { Route, Switch, useHistory, useRouteMatch } from 'react-router';
import { AppBar, Toolbar, IconButton, Container } from '@material-ui/core';
import {
  DarkModeToggle,
  LocaleToggle,
  Flex,
  Logo,
  ToolbarSpacing,
} from '@chia/core';
import { useAppDispatch, walletApi } from '@chia/api-react';
import { t } from '@lingui/macro';
import { ExitToApp as ExitToAppIcon } from '@material-ui/icons';
import Wallets from '../wallet/Wallets';

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
  const history = useHistory();
  const { path } = useRouteMatch();
  const dispatch = useAppDispatch();

  async function handleLogout() {
    dispatch(walletApi.util.resetApiState());

    history.push('/');
  }

  return (
    <StyledRoot>
      <StyledAppBar position="fixed" color="transparent" elevation={0}>
        <Toolbar>
          <Container maxWidth="lg">
            <Flex>
              <StyledBrandWrapper>
                <Logo height={1} />
              </StyledBrandWrapper>
              <Flex flexGrow={1} alignItems="flex-end" gap={1} />
              <LocaleToggle />
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
