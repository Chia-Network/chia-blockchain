import React from 'react';
import { Trans } from '@lingui/macro';
import { Button, DialogActions, Flex, Form, TextField } from '@chia/core';
import { useOpenFullNodeConnectionMutation } from '@chia/api-react';
import { useForm } from 'react-hook-form';
import { Alert, Dialog, DialogTitle, DialogContent } from '@mui/material';

type Props = {
  open: boolean;
  onClose: (value?: any) => void;
};

type FormData = {
  host: string;
  port: string;
};

export default function FullNodeAddConnection(props: Props) {
  const { onClose, open } = props;
  const [openConnection, { error }] = useOpenFullNodeConnectionMutation();

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      host: '',
      port: '',
    },
  });

  function handleClose() {
    if (onClose) {
      onClose(true);
    }
  }

  async function handleSubmit(values: FormData) {
    const { host, port } = values;

    await openConnection({
      host, 
      port: Number.parseInt(port, 10),
    }).unwrap();

    handleClose();
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
      <Form methods={methods} onSubmit={handleSubmit}>
        <DialogTitle id="alert-dialog-title">
          <Trans>Connect to other peers</Trans>
        </DialogTitle>
        <DialogContent>
          <Flex gap={2} flexDirection="column">
            {error && <Alert severity="error">{error.message}</Alert>}

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
          <Button onClick={handleHide} variant="outlined" color="secondary">
            <Trans>Cancel</Trans>
          </Button>
          <Button variant="contained" color="primary" type="submit">
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
