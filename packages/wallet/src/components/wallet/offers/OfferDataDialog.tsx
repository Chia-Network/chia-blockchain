import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Box,
  Button,
  Grid,
  Dialog,
  DialogTitle,
  DialogContent,
  InputAdornment,
  TextField,
} from '@material-ui/core';
import { CopyToClipboard, DialogActions } from '@chia/core';

type Props = {
  offerData: string;
  open: boolean;
  onClose: (value: boolean) => void;
};

export default function OfferDataDialog(props: Props) {
  const {
    onClose,
    open,
    offerData,
  } = props;

  function handleClose() {
    onClose(false);
  }

  return (
    <Dialog
      onClose={handleClose}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      maxWidth="md"
      open={open}
      fullWidth
    >
      <DialogTitle id="alert-dialog-title">
        <Trans>Offer Data</Trans>
      </DialogTitle>

      <DialogContent dividers>
        <Grid item xs={12}>
          <Box display="flex">
            <Box flexGrow={1}>
              <TextField
                label={<Trans>Offer Data</Trans>}
                value={offerData}
                variant="filled"
                InputProps={{
                  readOnly: true,
                  endAdornment: (
                    <InputAdornment position="end">
                      <CopyToClipboard value={offerData} />
                    </InputAdornment>
                  ),
                }}
                maxRows={10}
                fullWidth
                multiline
              />
            </Box>
          </Box>
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={handleClose}
          color="primary"
          variant="contained"
        >
          <Trans>OK</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}

OfferDataDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
