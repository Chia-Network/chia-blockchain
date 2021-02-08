import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, More } from '@chia/core';
import { createTeleporter } from 'react-teleporter';
import { useDispatch } from 'react-redux';
import { useHistory } from 'react-router-dom';
import { Button, MenuItem, Box, ListItemIcon, Typography } from '@material-ui/core';
import { Refresh as RefreshIcon, Folder as FolderIcon, Add as AddIcon } from '@material-ui/icons';
import {
  refreshPlots,
} from '../../modules/harvesterMessages';
import PlotAddDirectoryDialog from './PlotAddDirectoryDialog';
import useOpenDialog from '../../hooks/useOpenDialog';

const PlotHeaderTeleporter = createTeleporter();

export const PlotHeaderSource = PlotHeaderTeleporter.Source;

export const PlotHeaderTarget = PlotHeaderTeleporter.Target;

export default function PlotHeader() {
  const history = useHistory();
  const dispatch = useDispatch();
  const openDialog = useOpenDialog();

  function handleRefreshPlots() {
    dispatch(refreshPlots());
  }

  function handleAddPlot() {
    history.push('/dashboard/plot/add');
  }

  function handleAddPlotDirectory() {
    openDialog((
      <PlotAddDirectoryDialog />
    ));
  }

  return (
    <div>
      <Flex alignItems="center">
        <Flex flexGrow={1} />
        <div>
          <Button color="primary" variant="contained" onClick={handleAddPlot} startIcon={<AddIcon />}>
            <Trans>Add a Plot</Trans>
          </Button>
          {' '}
          <More>
            {({ onClose }) => (
              <Box>
                <MenuItem onClick={() => { onClose(); handleRefreshPlots(); }}>
                  <ListItemIcon>
                    <RefreshIcon fontSize="small" />
                  </ListItemIcon>
                  <Typography variant="inherit" noWrap>
                    <Trans>Refresh Plots</Trans>
                  </Typography>
                </MenuItem>
                <MenuItem onClick={() => { onClose(); handleAddPlotDirectory(); }}>
                  <ListItemIcon>
                    <FolderIcon fontSize="small" />
                  </ListItemIcon>
                  <Typography variant="inherit" noWrap>
                    <Trans>Add Plot Directory</Trans>
                  </Typography>
                </MenuItem>
              </Box>
            )}
          </More>
        </div>
      </Flex>
    </div>
  );
}
