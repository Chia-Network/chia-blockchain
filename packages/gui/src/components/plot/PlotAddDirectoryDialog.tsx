import React from 'react';
import { Trans } from '@lingui/macro';
import { Folder as FolderIcon, Delete as DeleteIcon } from '@mui/icons-material';
import {
  Avatar,
  Box,
  Dialog,
  DialogActions,
  DialogTitle,
  DialogContent,
  IconButton,
  List,
  ListItem,
  ListItemAvatar,
  ListItemSecondaryAction,
  ListItemText,
  Typography,
} from '@mui/material';
import { useShowError, Button, Suspender } from '@chia/core';
import { useAddPlotDirectoryMutation, useRemovePlotDirectoryMutation, useGetPlotDirectoriesQuery } from '@chia/api-react';
import useSelectDirectory from '../../hooks/useSelectDirectory';

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function PlotAddDirectoryDialog(props: Props) {
  const { onClose, open } = props;
  const [addPlotDirectory] = useAddPlotDirectoryMutation();
  const [removePlotDirectory] = useRemovePlotDirectoryMutation();
  const { data: directories, isLoading } = useGetPlotDirectoriesQuery();
  const showError = useShowError();
  const selectDirectory = useSelectDirectory({
    buttonLabel: 'Select Plot Directory',
  });

  if (isLoading) {
    return (
      <Suspender />
    );
  }

  function handleClose() {
    onClose();
  }

  function handleDialogClose(event: any, reason: any) {
    if (reason !== 'backdropClick' || reason !== 'EscapeKeyDown') {
      onClose();
    }}

  async function removePlotDir(dirname: string) {
    try {
      await removePlotDirectory({
        dirname,
      }).unwrap();
    } catch (error: any) {
      showError(error);
    }
  }

  async function handleSelectDirectory() {
    const dirname = await selectDirectory();
    if (dirname) {
      try {
        await addPlotDirectory({
          dirname,
        }).unwrap();
      } catch (error: any) {
        showError(error);
      }
    }
  }

  return (
    <Dialog
      onClose={handleDialogClose}
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
            {directories?.map((dir: string) => (
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
