import React from 'react';
import useMode from '../../hooks/useMode';
import Mode from '../../constants/Mode';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { Flex, Logo, Card } from '@chia/core';
import { AccountBalanceWallet as AccountBalanceWalletIcon } from '@material-ui/icons';
import { Typography, Container, Grid } from '@material-ui/core';

const StyledCardContent = styled.div`
  padding: 3rem 0rem;
`;

const StyledContainer = styled(Container)`
  padding-bottom: 1rem;
`;

const StyledGridItem = styled(Grid)`
  display: flex;
  flex-direction: column;
`;

export default function AppSelectMode() {
  const [mode, setMode] = useMode();

  const handleModeChange = (newMode: Mode) => {
    setMode(newMode);
  };

  return (
    <StyledContainer maxWidth="lg">
      <Flex flexDirection="column" alignItems="center" gap={3}>
        <Logo width={130} />
        
        <Typography variant="h5" component="h1">
          <Trans>Select Your Client Mode</Trans>
        </Typography>

        <Grid container spacing={3} alignItems="stretch">
          <Grid xs={12} sm={6} item>
            <Card onSelect={() => handleModeChange(Mode.FARMING)} fullHeight>
              <StyledCardContent>
                <Flex flexDirection="column" gap={2} alignItems="center">
                  <AccountBalanceWalletIcon fontSize="large" />

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
          <Grid xs={12} sm={6} item>
            <Card onSelect={() => handleModeChange(Mode.WALLET)} fullHeight>
              <StyledCardContent>
                <Flex flexDirection="column" gap={2} alignItems="center">
                  <AccountBalanceWalletIcon fontSize="large" />

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
        </Grid>

        <Typography>
          <Trans>You can always change your mode later in the settings</Trans>
        </Typography>
      </Flex>
    </StyledContainer>
  );
}
