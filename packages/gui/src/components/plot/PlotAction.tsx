import React from 'react';
import { Trans } from '@lingui/macro';
import { ConfirmDialog, More, useOpenDialog } from '@chia/core';
import { Box, ListItemIcon, MenuItem, Typography } from '@material-ui/core';
import { DeleteForever as DeleteForeverIcon } from '@material-ui/icons';
import { useDeletePlotMutation } from '@chia/api-react';
import type { Plot } from '@chia/api';

type Props = {
  plot: Plot;
};

export default function PlotAction(props: Props) {
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
        onConfirm={() => deletePlot({ filename }).unwrap()}
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
      {({ onClose }) => (
        <Box>
          <MenuItem
            onClick={() => {
              onClose();
              handleDeletePlot();
            }}
          >
            <ListItemIcon>
              <DeleteForeverIcon fontSize="small" />
            </ListItemIcon>
            <Typography variant="inherit" noWrap>
              <Trans>Delete</Trans>
            </Typography>
          </MenuItem>
        </Box>
      )}
    </More>
  );
}
