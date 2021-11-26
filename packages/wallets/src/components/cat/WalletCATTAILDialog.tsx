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
import { CopyToClipboard, DialogActions, Loading } from '@chia/core';
import useWallet from '../../hooks/useWallet';

type Props = {
  walletId: number;
  open: boolean;
  onClose: (value: boolean) => void;
};

export default function WalletCATTAILDialog(props: Props) {
  const {
    onClose,
    open,
    walletId,
  } = props;

  const { wallet, loading } = useWallet(walletId);

  function handleClose() {
    onClose(false);
  }

  return (
    <Dialog
      onClose={handleClose}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      maxWidth="lg"
      open={open}
    >
      <DialogTitle id="alert-dialog-title">
        <Trans>Asset Id</Trans>
      </DialogTitle>

      <DialogContent dividers>
        {loading && (
          <Loading center />
        )}

        {!!wallet && (
          <Grid item xs={12}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  label={<Trans>Asset Id</Trans>}
                  value={wallet.meta?.assetId}
                  variant="filled"
                  InputProps={{
                    readOnly: true,
                    endAdornment: (
                      <InputAdornment position="end">
                        <CopyToClipboard value={wallet.meta?.assetId} />
                      </InputAdornment>
                    ),
                  }}
                  fullWidth
                  multiline
                />
              </Box>
            </Box>
          </Grid>
        )}
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

WalletCATTAILDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
