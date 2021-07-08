import React from 'react';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { ConfirmDialog, More } from '@hddcoin/core';
import { Box, ListItemIcon, MenuItem, Typography } from '@material-ui/core';
import { DeleteForever as DeleteForeverIcon } from '@material-ui/icons';
import { deletePlot } from '../../modules/harvesterMessages';
import type Plot from '../../types/Plot';
import useOpenDialog from '../../hooks/useOpenDialog';

type Props = {
  plot: Plot;
};

export default function PlotAction(props: Props) {
  const {
    plot: { filename },
  } = props;

  const dispatch = useDispatch();
  const openDialog = useOpenDialog();

  async function handleDeletePlot() {
    const deleteConfirmed = await openDialog(
      <ConfirmDialog
        title={<Trans>Delete Plot</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        confirmColor="danger"
      >
        <Trans>
          Are you sure you want to delete the plot? The plot cannot be
          recovered.
        </Trans>
      </ConfirmDialog>,
    );

    // @ts-ignore
    if (deleteConfirmed) {
      dispatch(deletePlot(filename));
    }
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
