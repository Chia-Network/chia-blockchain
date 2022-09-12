import React from 'react';
import { useNavigate } from 'react-router';
import { Trans } from '@lingui/macro';
import { Grid, Typography } from '@mui/material';
import {
  Share as ShareIcon,
  Speed as SpeedIcon,
  HomeWork as HomeWorkIcon,
} from '@mui/icons-material';
import { Flex } from '@chia/core';
import WalletCreateCard from './WalletCreateCard';

export default function WalletCreateList() {
  const navigate = useNavigate();

  function handleCreateDistributedIdentity() {
    navigate(`did`);
  }

  function handleCreateCAT() {
    navigate(`cat`);
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexGrow={1}>
        <Typography variant="h5">
          <Trans>Select Wallet Type</Trans>
        </Typography>
      </Flex>
      <Grid spacing={3} alignItems="stretch" container>
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            onSelect={handleCreateCAT}
            title={<Trans>Chia Asset Token</Trans>}
            icon={<HomeWorkIcon fontSize="large" color="primary" />}
          />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            onSelect={handleCreateDistributedIdentity}
            title={<Trans>Distributed Identity</Trans>}
            icon={<ShareIcon fontSize="large" color="primary" />}
          />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <WalletCreateCard
            title={<Trans>Rate Limited</Trans>}
            icon={<SpeedIcon fontSize="large" color="primary" />}
            disabled
          />
        </Grid>
      </Grid>
    </Flex>
  );

  /*
  return (
    <Grid container spacing={0}>
      <Grid item xs={12}>
        <div className={classes.cardTitle}>
          <Box display="flex">
            <Box flexGrow={1} className={classes.title}>
              <Typography component="h6" variant="h6">
                <Trans>Select Wallet Type</Trans>
              </Typography>
            </Box>
          </Box>
        </div>
        <List>
          <ListItem button onClick={select_option_cc}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText primary={<Trans>Coloured Coin</Trans>} />
          </ListItem>
          <ListItem button onClick={select_option_rl}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText primary={<Trans>Rate Limited</Trans>} />
          </ListItem>
          <ListItem button onClick={select_option_did}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText
              primary={
                <Trans>Distributed Identity</Trans>
              }
            />
          </ListItem>
        </List>
      </Grid>
    </Grid>
  );
  */
}
