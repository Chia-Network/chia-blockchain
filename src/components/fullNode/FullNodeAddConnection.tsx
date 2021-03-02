import React from 'react';
import { Trans } from '@lingui/macro';
import { Alert } from '@material-ui/lab';
import { useDispatch, useSelector } from 'react-redux';
import { Form, TextField } from '@chia/core';
import { useForm } from 'react-hook-form';
import { Button, Dialog, DialogTitle, DialogContent, DialogActions, Grid } from '@material-ui/core';
import { RootState } from '../../modules/rootReducer';
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

  const connectionError = useSelector(
    (state: RootState) => state.full_node_state.open_connection_error,
  );

  function handleClose() {
    if (onClose) {
      onClose(true);
    }
  }

  async function handleSubmit(values: FormData) {
    const { host, port } = values;
    await dispatch(openConnection(host, port));
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
    >
      <Form
        methods={methods}
        onSubmit={handleSubmit}
      >
        <DialogTitle id="alert-dialog-title">
          <Trans>Connect to other peers</Trans>
        </DialogTitle>
        <DialogContent>
          {connectionError && (
            <Alert severity="error">{connectionError}</Alert>
          )}
          
          <Grid spacing={2} container>
            <Grid xs={12} sm={10} md={8} lg={6} item>
              <TextField
                label={
                  <Trans>IP address / host</Trans>
                }
                name="host"
              />
            </Grid>
            <Grid xs={12} sm={10} md={8} lg={6} item>
              <TextField
                label={<Trans>Port</Trans>}
                name="port"
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
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
