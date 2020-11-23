import React from 'react';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { ConfirmDialog, More } from '@chia/core';
import { Box, ListItemIcon, MenuItem, Typography } from '@material-ui/core';
import {
  DeleteForever as DeleteForeverIcon,
} from '@material-ui/icons';
import {
  deletePlot,
} from '../../modules/harvesterMessages';
import type Plot from '../../types/Plot';
import useOpenDialog from '../../hooks/useOpenDialog';

type Props = {
  plot: Plot;
};

export default function PlotAction(props: Props) {
  const {
    plot: {
      filename,
    }
  } = props;

  const dispatch = useDispatch();
  const openDialog = useOpenDialog();

  async function handleDeletePlot() {
    const canDelete = await openDialog((
      <ConfirmDialog
        title={<Trans id="PlotAction.deleteTitle">Delete Plot</Trans>}
        confirmTitle={<Trans id="PlotAction.deleteButton">Delete</Trans>}
      >
        <Trans id="PlotAction.deleteDescription">
          Are you sure you want to delete the plot? The plot cannot be
          recovered.
        </Trans>
      </ConfirmDialog>
    ));

    // @ts-ignore
    if (canDelete) {
      dispatch(deletePlot(filename));
    }
  }

  return (
    <More>
      {({ onClose }) => (
        <Box>
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
