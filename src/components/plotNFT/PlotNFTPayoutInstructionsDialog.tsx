import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { Alert } from '@material-ui/lab';
import {
  CopyToClipboard,
  Flex,
  Link,
  Loading,
  TextField,
  Form,
} from '@chia/core';
import {
  Button,
  Dialog,
  DialogActions,
  DialogTitle,
  DialogContent,
  Typography,
} from '@material-ui/core';
import PlotNFT from '../../types/PlotNFT';
import PlotNFTExternal from '../../types/PlotNFTExternal';

type FormData = {
  pool_payout_instructions: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  nft: PlotNFT | PlotNFTExternal;
};

export default function PlotNFTPayoutInstructionsDialog(props: Props) {
  const { onClose, open, nft } = props;
  const {
    pool_state: {
      pool_config: { pool_payout_instructions },
    },
  } = nft;

  const [loading] = useState<boolean>(false);
  const [error] = useState<Error | undefined>(undefined);
  const [loginLink] = useState<string | undefined>(undefined);

  const methods = useForm<FormData>({
    mode: 'onChange',
    shouldUnregister: false,
    defaultValues: {
      pool_payout_instructions: pool_payout_instructions || '',
    },
  });

  function handleClose() {
    onClose();
  }

  function handleSubmit() {}

  return (
    <Dialog disableBackdropClick disableEscapeKeyDown maxWidth="md" open={open}>
      <DialogTitle>
        <Trans>Pool Payout Instructions</Trans>
      </DialogTitle>
      <DialogContent dividers>
        <Flex gap={2} flexDirection="column">
          {loading ? (
            <Loading center />
          ) : (
            <Flex flexDirection="column" gap={2}>
              {error && <Alert severity="error">{error.message}</Alert>}

              <Form methods={methods} onSubmit={handleSubmit}>
                <TextField
                  label={<Trans>Pool Payout Instructions</Trans>}
                  name="pool_payout_instructions"
                  variant="filled"
                  inputProps={{
                    readOnly: true,
                    spellCheck: false,
                  }}
                  fullWidth
                />
              </Form>

              <Typography variant="body2" color="textSecondary">
                <Trans>
                  These are the instructions for how the farmer wants to get
                  paid. By default this will be an XCH address, but it can be
                  set to any string with a size of less than 1024 characters, so
                  it can represent another blockchain or payment system
                  identifier.
                </Trans>{' '}
                <Link
                  target="_blank"
                  href="https://github.com/Chia-Network/pool-reference/blob/main/SPECIFICATION.md#payloadpayout_instructions"
                  noWrap
                >
                  <Trans>Learn More</Trans>
                </Link>
              </Typography>
            </Flex>
          )}
        </Flex>
      </DialogContent>
      <DialogActions>
        {loginLink && (
          <CopyToClipboard value={pool_payout_instructions} size="medium" />
        )}

        <Button onClick={handleClose} color="secondary">
          <Trans>OK</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}

PlotNFTPayoutInstructionsDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
