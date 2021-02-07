import React from 'react';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { ConfirmDialog, More } from '@chia/core';
import { Box, ListItemIcon, MenuItem, Typography } from '@material-ui/core';
import {
  DeleteForever as DeleteForeverIcon,
  Info as InfoIcon,
} from '@material-ui/icons';
import useOpenDialog from '../../../hooks/useOpenDialog';
import type PlotQueueItem from '../../../types/PlotQueueItem';
import PlotStatus from '../../../constants/PlotStatus';
import { stopPlotting } from '../../../modules/plotter_messages';
import PlotQueueLogDialog from './PlotQueueLogDialog';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueAction(props: Props) {
  const {
    queueItem: {
      id,
      state,
    }
  } = props;

  const dispatch = useDispatch();
  const openDialog = useOpenDialog();

  async function handleDeletePlot() {
    const canDelete = await openDialog((
      <ConfirmDialog
        title={<Trans id="PlotQueueAction.deleteTitle">Delete Plot</Trans>}
        confirmTitle={<Trans id="PlotQueueAction.deleteButton">Delete</Trans>}
      >
        <Trans id="PlotQueueAction.deleteDescription">
          Are you sure you want to delete the plot? The plot cannot be
          recovered.
        </Trans>
      </ConfirmDialog>
    ));

    // @ts-ignore
    if (canDelete) {
      dispatch(stopPlotting(id));
    }
  }

  function handleViewLog() {
    openDialog((
      <PlotQueueLogDialog id={id} />
    ));
  }

  return (
    <More>
      {({ onClose }) => (
        <Box>
          {state === PlotStatus.RUNNING && (
            <MenuItem onClick={() => { onClose(); handleViewLog(); }}>
              <ListItemIcon>
                <InfoIcon fontSize="small" />
              </ListItemIcon>
              <Typography variant="inherit" noWrap>
                View Log
              </Typography>
            </MenuItem>
          )}

          <MenuItem onClick={() => { onClose(); handleDeletePlot(); }}>
            <ListItemIcon>
              <DeleteForeverIcon fontSize="small" />
            </ListItemIcon>
            <Typography variant="inherit" noWrap>
              Delete
            </Typography>
          </MenuItem>
        </Box>
      )}
    </More>
  );
}
