import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Box,
  Dialog,
  DialogTitle,
  DialogContent,
  InputAdornment,
  TextField,
} from '@mui/material';
import {
  Button,
  CopyToClipboard,
  DialogActions,
  Loading,
  Link,
  Flex,
} from '@chia/core';
import useWallet from '../../hooks/useWallet';

type Props = {
  walletId: number;
  open?: boolean;
  onClose?: (value: boolean) => void;
};

export default function WalletCATTAILDialog(props: Props) {
  const { onClose = () => {}, open = false, walletId } = props;

  const { wallet, loading } = useWallet(walletId);

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
        <Trans>Asset Id</Trans>
      </DialogTitle>

      <DialogContent dividers>
        {loading && <Loading center />}

        {!!wallet && (
          <Flex flexDirection="column" gap={1}>
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
            <Link
              href={`https://www.taildatabase.com/tail/${wallet.meta?.assetId}`}
              target="_blank"
              variant="body2"
            >
              <Trans>Search on Tail Database</Trans>
            </Link>
          </Flex>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} color="primary" variant="contained">
          <Trans>OK</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}
