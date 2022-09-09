import React from 'react';
import { Trans } from '@lingui/macro';
import { ConfirmDialog, More, MenuItem, useOpenDialog } from '@chia/core';
import { Divider, ListItemIcon, Typography } from '@mui/material';
import {
  DeleteForever as DeleteForeverIcon,
  Info as InfoIcon,
} from '@mui/icons-material';
import { useStopPlottingMutation } from '@chia/api-react';
import type PlotQueueItem from '../../../types/PlotQueueItem';
import PlotStatus from '../../../constants/PlotStatus';
import PlotQueueLogDialog from './PlotQueueLogDialog';

export type PlotQueueActionProps = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueAction(props: PlotQueueActionProps) {
  const {
    queueItem: { id, state },
  } = props;

  const [stopPlotting] = useStopPlottingMutation();
  const openDialog = useOpenDialog();
  const canDelete = state !== PlotStatus.REMOVING;

  async function handleDeletePlot() {
    if (!canDelete) {
      return;
    }

    await openDialog(
      <ConfirmDialog
        title={<Trans>Delete Plot</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        confirmColor="danger"
        onConfirm={() =>
          stopPlotting({
            id,
          }).unwrap()
        }
      >
        <Trans>
          Are you sure you want to delete the plot? The plot cannot be
          recovered.
        </Trans>
      </ConfirmDialog>,
    );
  }

  function handleViewLog() {
    openDialog(<PlotQueueLogDialog id={id} />);
  }

  return (
    <More>
      {state === PlotStatus.RUNNING && [
        <MenuItem key="view-log" onClick={handleViewLog} close>
          <ListItemIcon>
            <InfoIcon fontSize="small" />
          </ListItemIcon>
          <Typography variant="inherit" noWrap>
            <Trans>View Log</Trans>
          </Typography>
        </MenuItem>,
        <Divider key="divider" />,
      ]}

      <MenuItem onClick={handleDeletePlot} disabled={!canDelete} close>
        <ListItemIcon>
          <DeleteForeverIcon fontSize="small" />
        </ListItemIcon>
        <Typography variant="inherit" noWrap>
          <Trans>Delete</Trans>
        </Typography>
      </MenuItem>
    </More>
  );
}
