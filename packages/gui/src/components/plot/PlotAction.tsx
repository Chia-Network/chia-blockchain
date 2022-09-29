import React from 'react';
import { Trans } from '@lingui/macro';
import { ConfirmDialog, More, MenuItem, useOpenDialog } from '@chia/core';
import { ListItemIcon, Typography } from '@mui/material';
import { DeleteForever as DeleteForeverIcon } from '@mui/icons-material';
import { useDeletePlotMutation } from '@chia/api-react';
import type { Plot } from '@chia/api';

export type PlotActionProps = {
  plot: Plot;
};

export default function PlotAction(props: PlotActionProps) {
  const {
    plot: { filename },
  } = props;

  const openDialog = useOpenDialog();
  const [deletePlot] = useDeletePlotMutation();

  async function handleDeletePlot() {
    await openDialog(
      <ConfirmDialog
        title={<Trans>Delete Plot</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        confirmColor="danger"
        onConfirm={() => {
          return deletePlot({ filename }).unwrap();
        }}
      >
        <Trans>
          Are you sure you want to delete the plot? The plot cannot be
          recovered.
        </Trans>
      </ConfirmDialog>,
    );
  }

  return (
    <More>
      <MenuItem onClick={handleDeletePlot} close>
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
