import React from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { Flex, Logo, Card, useMode, Mode, Tooltip } from '@chia/core';
import { 
  AccountBalanceWallet as AccountBalanceWalletIcon, 
  Eco as EcoIcon,
  Settings as SettingsIcon,
} from '@material-ui/icons';
import { Box, Typography, Container, Grid } from '@material-ui/core';

const StyledSettingsIcon = styled(SettingsIcon)`
  vertical-align: sub;
`;

const StyledCardContent = styled(Box)`
  padding: 3rem 0rem;
`;

const StyledContainer = styled(Container)`
  padding-bottom: 1rem;
`;

const StyledGridItem = styled(Grid)`
  display: flex;
  flex-direction: column;
`;

const StyledEcoIcon = styled(EcoIcon)`
  font-size: 3.4rem;
`;

const StyledAccountBalanceWalletIcon = styled(AccountBalanceWalletIcon)`
  font-size: 3.4rem;
`;

export default function AppSelectMode() {
  const [_mode, setMode] = useMode();

  const handleModeChange = (newMode: Mode) => {
    setMode(newMode);
  };

  return (
    <StyledContainer maxWidth="sm">
      <Flex flexDirection="column" alignItems="center" gap={3}>
        <Logo width={130} />
        
        <Typography variant="h5" component="h1">
          <Trans>Select Your Client Mode</Trans>
        </Typography>

        <Grid container spacing={5} alignItems="stretch">
          <Grid xs={12} sm={6} item>
            <Card onSelect={() => handleModeChange(Mode.WALLET)} fullHeight>
              <StyledCardContent>
                <Flex flexDirection="column" gap={2} alignItems="center">
                  <StyledAccountBalanceWalletIcon />

                  <Typography variant="h5" align="center">
                    <Trans>Wallet Mode</Trans>
                  </Typography>

                  <Flex flexDirection="column" gap={0.5}>
                    <Typography variant="body2" align="center">
                      <Trans>Store and Send XCH</Trans>
                    </Typography>
                    <Typography variant="body2" align="center">
                      <Trans>Manage CAT tokens</Trans>
                    </Typography>
                    <Typography variant="body2" align="center">
                      <Trans>Trade tokens</Trans>
                    </Typography>
                  </Flex>
                </Flex>
              </StyledCardContent>
            </Card>
          </Grid>
          <Grid xs={12} sm={6} item>
            <Card onSelect={() => handleModeChange(Mode.FARMING)} fullHeight>
              <StyledCardContent>
                <Flex flexDirection="column" gap={2} alignItems="center">
                  <StyledEcoIcon />

                  <Typography variant="h5" align="center">
                    <Trans>Farming Mode</Trans>
                  </Typography>

                  <Flex flexDirection="column" gap={0.5}>
                    <Typography variant="body2" align="center">
                      <Trans>Wallet Mode</Trans>
                    </Typography>
                    <Typography variant="body2" align="center">
                      <Trans>+</Trans>
                    </Typography>
                    <Typography variant="body2" align="center">
                      <Trans>Create &amp; Manage plots</Trans>
                    </Typography>
                    <Typography variant="body2" align="center">
                      <Trans>Join farming pools</Trans>
                    </Typography>
                  </Flex>
                </Flex>
              </StyledCardContent>
            </Card>
          </Grid>
        </Grid>

        <Tooltip title={<Trans>Settings are located at the upper right corner</Trans>}>
        <Typography>
          <Trans>You can always change your mode later in the settings</Trans>
          &nbsp;
          <StyledSettingsIcon fontSize="small" />
        </Typography>
        </Tooltip>
      </Flex>
    </StyledContainer>
  );
}
