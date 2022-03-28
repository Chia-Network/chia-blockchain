import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { Button, Flex, More, useOpenDialog } from '@chia/core';
import { createTeleporter } from 'react-teleporter';
import { useNavigate, useParams } from 'react-router-dom';
import {
  MenuItem,
  Box,
  ListItemIcon,
  Typography,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  Folder as FolderIcon,
  Add as AddIcon,
} from '@mui/icons-material';
import { useRefreshPlotsMutation } from '@chia/api-react';
import PlotAddDirectoryDialog from './PlotAddDirectoryDialog';

type Props = {
  children?: ReactNode;
};

const PlotHeaderTeleporter = createTeleporter();

export const PlotHeaderSource = PlotHeaderTeleporter.Source;

export const PlotHeaderTarget = PlotHeaderTeleporter.Target;

export default function PlotHeader(props: Props) {
  const { children } = props;

  const navigate = useNavigate();
  const openDialog = useOpenDialog();
  const [refreshPlots] = useRefreshPlotsMutation();

  async function handleRefreshPlots() {
    await refreshPlots().unwrap();
  }

  function handleAddPlot() {
    navigate('/dashboard/plot/add');
  }

  function handleAddPlotDirectory() {
    openDialog(<PlotAddDirectoryDialog />);
  }

  return (
    <div>
      <Flex alignItems="center">
        <Flex flexGrow={1}>{children}</Flex>
        <div>
          <Button
            color="primary"
            variant="outlined"
            onClick={handleAddPlot}
            startIcon={<AddIcon />}
          >
            <Trans>Add a Plot</Trans>
          </Button>{' '}
          <More>
            {({ onClose }) => (
              <Box>
                <MenuItem
                  onClick={() => {
                    onClose();
                    handleRefreshPlots();
                  }}
                >
                  <ListItemIcon>
                    <RefreshIcon fontSize="small" />
                  </ListItemIcon>
                  <Typography variant="inherit" noWrap>
                    <Trans>Refresh Plots</Trans>
                  </Typography>
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    onClose();
                    handleAddPlotDirectory();
                  }}
                >
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
