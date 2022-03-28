import React, { useEffect, useState, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import {
  Dialog,
  DialogActions,
  DialogTitle,
  DialogContent,
  LinearProgress,
  Typography,
} from '@mui/material';
import { Button, Flex, Log } from '@chia/core';
import { useGetPlotQueueQuery, useThrottleQuery } from '@chia/api-react';
import styled from 'styled-components';

const StyledLinearProgress = styled(LinearProgress)`
  height: 10px;
  border-radius: 0;
  width: 100%;
`;

type Props = {
  id: string;
  open: boolean;
  onClose: () => void;
};

export default function PlotQueueLogDialog(props: Props) {
  const { id, open, onClose } = props;
  const { data: queue } = useThrottleQuery(useGetPlotQueueQuery, undefined, undefined, {
    wait: 5000,
  });

  const queueItem = queue?.find((item) => item.id === id);
  const [log, setLog] = useState<ReactNode>(<Trans>Loading...</Trans>);

  useEffect(() => {
    if (queueItem && queueItem.log) {
      setLog(queueItem.log.trim());
    }
  }, [queueItem]);

  function handleClose(event: any, reason: any) {
    if (reason !== 'backdropClick' || reason !== 'EscapeKeyDown') {
      onClose();
    }}

  return (
    <Dialog
      maxWidth="md"
      aria-labelledby="confirmation-dialog-title"
      onClose={handleClose}
      open={open}
    >
      <DialogTitle id="confirmation-dialog-title">
        <Trans>View Log</Trans>
      </DialogTitle>

      <DialogContent dividers>
        <Flex flexDirection="column" gap={2}>
          {!!queueItem && queueItem.progress !== undefined && (
            <Flex gap={1} alignItems="center">
              <Flex flexGrow={1}>
                <StyledLinearProgress
                  variant="determinate"
                  value={queueItem.progress * 100}
                  color="secondary"
                />
              </Flex>
              <Flex>
                <Typography variant="body2" color="textSecondary">
                  {`${Math.round(queueItem.progress * 100)}%`}
                </Typography>
              </Flex>
            </Flex>
          )}
          <Log>{log}</Log>
        </Flex>
      </DialogContent>
      <DialogActions>
        <Button autoFocus onClick={handleClose} color="secondary">
          <Trans>Close</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}

PlotQueueLogDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
