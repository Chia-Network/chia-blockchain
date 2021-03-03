import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Alert } from '@material-ui/lab';
import { useDispatch } from 'react-redux';
import { DialogActions, Flex, Form, TextField } from '@chia/core';
import { useForm } from 'react-hook-form';
import { Button, Dialog, DialogTitle, DialogContent } from '@material-ui/core';
import { openConnection } from '../../modules/fullnodeMessages';

type Props = {
  open: boolean,
  onClose: (value?: any) => void,
};

type FormData = {
  host: string;
  port: string;
};

export default function FullNodeAddConnection(props: Props) {
  const { onClose, open } = props;
  const dispatch = useDispatch();
  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      host: '',
      port: '',
    },
  });

  const [error, setError] = useState<Error | null>(null);

  function handleClose() {
    if (onClose) {
      onClose(true);
    }
  }

  async function handleSubmit(values: FormData) {
    const { host, port } = values;
    setError(null);

    try {
      await dispatch(openConnection(host, port));
      handleClose();
    } catch (error) {
      setError(error);
    }
  }

  function handleHide() {
    if (onClose) {
      onClose();
    }
  }

  return (
    <Dialog
      onClose={handleHide}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      open={open}
      maxWidth="xs"
      fullWidth
    >
      <Form
        methods={methods}
        onSubmit={handleSubmit}
      >
        <DialogTitle id="alert-dialog-title">
          <Trans>Connect to other peers</Trans>
        </DialogTitle>
        <DialogContent>          
          <Flex gap={2} flexDirection="column">
            {error && (
              <Alert severity="error">{error.message}</Alert>
            )}

            <TextField
              label={<Trans>IP address / host</Trans>}
              name="host"
              variant="filled"
            />
            <TextField
              label={<Trans>Port</Trans>}
              name="port"
              type="number"
              variant="filled"
            />
          </Flex>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={handleHide}
            variant="contained"
            color="secondary"
          >
            <Trans>Cancel</Trans>
          </Button>
          <Button
            variant="contained"
            color="primary"
            type="submit"
          >
            <Trans>Connect</Trans>
          </Button>
        </DialogActions>
      </Form>
    </Dialog>
  );
}

FullNodeAddConnection.defaultProps = {
  open: false,
  onClose: () => {},
};
