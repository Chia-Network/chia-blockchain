import React, { useEffect, useState } from 'react';
import { Button, Dialog, DialogActions, DialogTitle, DialogContent } from '@material-ui/core';
import { useSelector } from 'react-redux';
import { Log } from '@chia/core';
import type { RootState } from '../../../modules/rootReducer';

type Props = {
  id: string;
  open: boolean;
  onClose: () => void;
};

export default function PlotQueueLogDialog(props: Props) {
  const { id, open, onClose } = props;
  const queueItem = useSelector((state: RootState) => state.plot_queue.queue.find((item) => item.id === id));
  const [log, setLog] = useState<string>('Loading...');

  useEffect(() => {
    if (queueItem && queueItem.log) {
      setLog(queueItem.log.trim());
    }
  }, [queueItem]);

  function handleClose() {
    onClose();
  }

  return (
    <Dialog
      disableBackdropClick
      disableEscapeKeyDown
      maxWidth="md"
      aria-labelledby="confirmation-dialog-title"
      onClose={handleClose}
      open={open}
    >
      <DialogTitle id="confirmation-dialog-title">
        View Log
      </DialogTitle>
      <DialogContent dividers>
        <Log>{log}</Log>
      </DialogContent>
      <DialogActions>
        <Button autoFocus onClick={handleClose} color="secondary">
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}

PlotQueueLogDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
