import React, { ReactNode, Suspense, useMemo } from 'react';
import styled from 'styled-components';
import { useNavigate, Outlet } from 'react-router-dom';
import { t, Trans } from '@lingui/macro';
import { AppBar, Toolbar, Drawer, Container, IconButton, MenuItem, Typography } from '@mui/material';
import Flex from '../Flex';
import Logo from '../Logo';
import ToolbarSpacing from '../ToolbarSpacing';
import Loading from '../Loading';
import { useLogout, useGetLoggedInFingerprintQuery } from '@chia/api-react';
import { ExitToApp as ExitToAppIcon, Notifications } from '@mui/icons-material';
import Settings from '../Settings';
import Tooltip from '../Tooltip';
import { DropdownIconButton } from '../Dropdown';
// import LayoutFooter from '../LayoutMain/LayoutFooter';

const StyledRoot = styled(Flex)`
  height: 100%;
  // overflow: hidden;
`;

const StyledContainer = styled(Container)`
  padding-top: ${({ theme }) => theme.spacing(2)};
  padding-bottom: ${({ theme }) => theme.spacing(2)};
`;

const StyledAppBar = styled(AppBar)`
  border-bottom: 1px solid ${({ theme }) => theme.palette.divider};
  width: ${({ theme, drawer }) => drawer ? `calc(100% - ${theme.drawer.width})` : '100%'};
  margin-left: ${({ theme, drawer }) => drawer ? theme.drawer.width : 0};
  z-index: ${({ theme }) => theme.zIndex.drawer + 1};};
`;

const StyledDrawer = styled(Drawer)`
  z-index: ${({ theme }) => theme.zIndex.drawer + 2};
  width: ${({ theme }) => theme.drawer.width};
  flex-shrink: 0;

  > div {
    width: ${({ theme }) => theme.drawer.width};
    // border-width: 0px;
  }
`;

const StyledBody = styled(Flex)`
  min-width: 0;
`;

const StyledBrandWrapper = styled(Flex)`
  height: 64px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
`;

const StyledToolbar = styled(Toolbar)`
  padding-left: ${({ theme }) => theme.spacing(4)};
  padding-right: ${({ theme }) => theme.spacing(4)};
`;

const StyledInlineTypography = styled(Typography)`
  display: inline-block;
`;

export type LayoutDashboardProps = {
  children?: ReactNode;
  sidebar?: ReactNode;
  outlet?: boolean;
  settings?: ReactNode;
};

export default function LayoutDashboard(props: LayoutDashboardProps) {
  const { children, sidebar, settings, outlet = false } = props;

  const navigate = useNavigate();
  const logout = useLogout();
  const { data: fingerprint } = useGetLoggedInFingerprintQuery();
  const partial = useMemo(() => {
    if (fingerprint) {
      // return last 6 digits of fingerprint
      return `(...${fingerprint.toString().slice(-6)})`;
    }

    return null;
  }, [fingerprint]);

  async function handleLogout() {
    await logout();

    navigate('/');
  }

  return (
    <StyledRoot>
      <Suspense fallback={<Loading center />}>
        {sidebar ? (
          <>
            <StyledAppBar position="fixed" color="transparent" elevation={0} drawer>
              <StyledToolbar>
                  <Flex alignItems="center" width="100%">
                    <Typography variant="h4">
                      <Trans>
                        Wallet
                      </Trans>
                      &nbsp;
                      {partial && (
                        <StyledInlineTypography color="textSecondary" variant="h4">
                          {partial}
                        </StyledInlineTypography>
                      )}
                    </Typography>
                    <Flex flexGrow={1} />
                    <DropdownIconButton
                      icon={<Notifications />}
                      title={t`Notifications`}
                    >
                      {({ onClose }) => (
                        <MenuItem onClick={onClose}>
                          CAT Wallet TEST is now available
                        </MenuItem>
                      )}
                    </DropdownIconButton>
                    &nbsp;
                    <Tooltip title={<Trans>Logout</Trans>}>
                      <IconButton onClick={handleLogout} title={t`Log Out`}>
                        <ExitToAppIcon />
                      </IconButton>
                    </Tooltip>
                  </Flex>
              </StyledToolbar>
            </StyledAppBar>
            <StyledDrawer variant="permanent">
              {sidebar}
            </StyledDrawer>
          </>
        ) : (
          <StyledAppBar position="fixed" color="transparent" elevation={0}>
            <StyledToolbar>
              <Container maxWidth="lg">
                <Flex alignItems="center">
                  <Logo width="100px" />
                  <Flex flexGrow={1} />
                  <Tooltip title={<Trans>Logout</Trans>}>
                    <IconButton color="inherit" onClick={handleLogout} title={t`Log Out`}>
                      <ExitToAppIcon />
                    </IconButton>
                  </Tooltip>
                  <Settings>
                    {settings}
                  </Settings>
                </Flex>
              </Container>
            </StyledToolbar>
          </StyledAppBar>
        )}

        <StyledBody flexDirection="column" flexGrow={1}>
          <ToolbarSpacing />
          <Flex flexDirection="column" gap={2} flexGrow={1} overflow="auto">
            <Suspense fallback={<Loading center />}>
              {outlet ? <Outlet /> : children}
            </Suspense>
            {/* <LayoutFooter /> */}
          </Flex>
        </StyledBody>
      </Suspense>
    </StyledRoot>
  );
}
