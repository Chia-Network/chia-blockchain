import React from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router';
import { useRefreshPlotsMutation } from '@chia/api-react';
import { Button, Flex, useOpenDialog, MenuItem, More } from '@chia/core';
import { ListItemIcon, Typography } from '@mui/material';
import { Add, Refresh } from '@mui/icons-material';
import PlotOverviewCards from './PlotOverviewCards';
import PlotHarvesters from '../PlotHarvesters';
import PlotPlotting from '../PlotPlotting';
import PlotAddDirectoryDialog from '../PlotAddDirectoryDialog';

export default function PlotOverviewPlots() {
  const navigate = useNavigate();
  const openDialog = useOpenDialog();
  const [refreshPlots] = useRefreshPlotsMutation();

  function handleAddPlot() {
    navigate('/dashboard/plot/add');
  }

  function handleAddPlotDirectory() {
    openDialog(<PlotAddDirectoryDialog />);
  }

  async function handleRefreshPlots() {
    await refreshPlots().unwrap();
  }

  return (
    <Flex flexDirection="column" gap={4}>
      <Flex flexDirection="column" gap={2}>
        <Flex flexGrow={1} justifyContent="space-between">
          <Typography variant="h5">
            <Trans>Plotting Manager</Trans>
          </Typography>
          <Flex alignItems="center">
            <Button variant="outlined" color="primary" onClick={handleAddPlot}>
              <Trans>+ Add a Plot</Trans>
            </Button>
            &nbsp;
            <More>
              <MenuItem onClick={handleAddPlotDirectory} close>
                <ListItemIcon>
                  <Add fontSize="small" />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Add Plot Directory</Trans>
                </Typography>
              </MenuItem>
              <MenuItem onClick={handleRefreshPlots} close>
                <ListItemIcon>
                  <Refresh fontSize="small" />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Refresh Plots</Trans>
                </Typography>
              </MenuItem>
            </More>
          </Flex>
        </Flex>
        <PlotOverviewCards />
      </Flex>
      <PlotPlotting />
      <PlotHarvesters />
    </Flex>
  );
}
