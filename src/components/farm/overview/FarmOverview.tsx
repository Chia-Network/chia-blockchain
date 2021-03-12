import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, More } from '@chia/core';
import { useSelector } from 'react-redux';
import { Box, MenuItem, CircularProgress, ListItemIcon, Typography } from '@material-ui/core';
import { Settings as SettingsIcon } from '@material-ui/icons';
import type { RootState } from '../../../modules/rootReducer';
import FarmOverviewHero from './FarmOverviewHero';
import FarmOverviewCards from './FarmOverviewCards';
import FarmManageFarmingRewards from '../FarmManageFarmingRewards';
import useOpenDialog from '../../../hooks/useOpenDialog';

export default function FarmOverview() {
  const openDialog = useOpenDialog();
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );
  const loading = !plots;
  const hasPlots = !!plots && plots.length > 0;

  function handleManageFarmingRewards() {
    // @ts-ignore
    openDialog((
      <FarmManageFarmingRewards />
    ));
  }

  return (
    <>
      <Flex gap={2} alignItems="center">
        <Flex flexGrow={1}>
          <Typography variant="h5" gutterBottom>
            <Trans>Your Farm Overview</Trans>
          </Typography>
        </Flex>
        <More>
          {({ onClose }) => (
            <Box>
              <MenuItem onClick={() => { onClose(); handleManageFarmingRewards(); }}>
                <ListItemIcon>
                  <SettingsIcon fontSize="small" />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Manage Farming Rewards</Trans>
                </Typography>
              </MenuItem>
            </Box>
          )}
        </More>
      </Flex>

      {loading ? (
        <CircularProgress />
      ) : (hasPlots ? (
        <FarmOverviewCards />
      ) : (
        <FarmOverviewHero />
      ))}
    </>
  );
}
