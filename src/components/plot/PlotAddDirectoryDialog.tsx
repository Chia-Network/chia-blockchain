import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Folder as FolderIcon,
  Delete as DeleteIcon,
} from '@material-ui/icons';
import { Avatar, Box, Button, Dialog, DialogActions, DialogTitle, DialogContent, IconButton, List, ListItem, ListItemAvatar, ListItemSecondaryAction, ListItemText, Typography } from '@material-ui/core';
import { useSelector, useDispatch } from 'react-redux';
import {
  add_plot_directory_and_refresh,
  remove_plot_directory_and_refresh,
} from '../../modules/message';
import type { RootState } from '../../modules/rootReducer';
import useSelectDirectory from '../../hooks/useSelectDirectory';

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function PlotAddDirectoryDialog(props: Props) {
  const { onClose, open } = props;
  const dispatch = useDispatch();
  const selectDirectory = useSelectDirectory({
    buttonLabel: 'Select Plot Directory',
  });

  const directories = useSelector(
    (state: RootState) => state.farming_state.harvester.plot_directories ?? [],
  );

  function handleClose() {
    onClose();
  }

  function removePlotDir(dir: string) {
    dispatch(remove_plot_directory_and_refresh(dir));
  }

  async function handleSelectDirectory() {
    const directory = await selectDirectory();
    if (directory) {
      dispatch(add_plot_directory_and_refresh(directory));
    }
  }

  return (
    <Dialog
      disableBackdropClick
      disableEscapeKeyDown
      maxWidth="md"
      aria-labelledby="confirmation-dialog-title"
      open={open}
    >
      <DialogTitle id="confirmation-dialog-title">
        <Trans>Add a plot</Trans>
      </DialogTitle>
      <DialogContent dividers>
        <Typography>
          <Trans>
            This allows you to add a directory that has plots in it. If you have
            not created any plots, go to the plotting screen.
          </Trans>
        </Typography>
        <Box display="flex">
          <List dense>
            {directories.map((dir: string) => (
              <ListItem key={dir}>
                <ListItemAvatar>
                  <Avatar>
                    <FolderIcon />
                  </Avatar>
                </ListItemAvatar>
                <ListItemText primary={dir} />
                <ListItemSecondaryAction>
                  <IconButton
                    edge="end"
                    aria-label="delete"
                    onClick={() => removePlotDir(dir)}
                  >
                    <DeleteIcon />
                  </IconButton>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
          </List>
        </Box>
        <Box display="flex">
          <Box>
            <Button
              onClick={handleSelectDirectory}
              variant="contained"
              color="primary"
            >
              <Trans>Add plot directory</Trans>
            </Button>
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button autoFocus onClick={handleClose} color="secondary">
          <Trans>Close</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}

PlotAddDirectoryDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
