import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, More, useOpenDialog, MenuItem } from '@chia/core';
import { ListItemIcon, Typography } from '@mui/material';
import { Settings as SettingsIcon } from '@mui/icons-material';
import FarmManageFarmingRewards from './FarmManageFarmingRewards';

export default function FarmHeader() {
  const openDialog = useOpenDialog();

  function handleManageFarmingRewards() {
    // @ts-ignore
    openDialog(<FarmManageFarmingRewards />);
  }

  return (
    <Flex gap={2} alignItems="center">
      <Flex flexGrow={1}>
        <Typography variant="h5">
          <Trans>Your Farm Overview</Trans>
        </Typography>
      </Flex>
      <More>
        <MenuItem onClick={handleManageFarmingRewards} close>
          <ListItemIcon>
            <SettingsIcon fontSize="small" />
          </ListItemIcon>
          <Typography variant="inherit" noWrap>
            <Trans>Manage Farming Rewards</Trans>
          </Typography>
        </MenuItem>
      </More>
    </Flex>
  );
}
