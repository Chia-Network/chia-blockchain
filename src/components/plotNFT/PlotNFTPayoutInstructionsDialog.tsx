import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useForm, useWatch } from 'react-hook-form';
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
  InputAdornment,
} from '@material-ui/core';
import PlotNFT from '../../types/PlotNFT';
import PlotNFTExternal from '../../types/PlotNFTExternal';
import usePayoutAddress from '../../hooks/usePayoutAddress';

type FormData = {
  payoutAddress: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  nft: PlotNFT | PlotNFTExternal;
};

export default function PlotNFTPayoutInstructionsDialog(props: Props) {
  const { onClose, open, nft } = props;
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | undefined>(undefined);
  const { payoutAddress, setPayoutAddress } = usePayoutAddress(nft);

  const methods = useForm<FormData>({
    mode: 'onChange',
    shouldUnregister: false,
    defaultValues: {
      payoutAddress: payoutAddress || '',
    },
  });

  const currentPayoutAddress = useWatch<string>({
    name: 'payoutAddress',
    control: methods.control,
  })

  function handleClose() {
    onClose();
  }

  async function handleSubmit(values) {
    const { payoutAddress } = values;
    try {
      setError(undefined);
      setLoading(true);
      await setPayoutAddress(payoutAddress);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog disableBackdropClick disableEscapeKeyDown maxWidth="md" open={open}>
      <Form methods={methods} onSubmit={handleSubmit}>
        <DialogTitle>
          <Trans>Edit Payout Instructions</Trans>
        </DialogTitle>
        <DialogContent dividers>
          <Flex gap={2} flexDirection="column">
            {loading ? (
              <Loading center />
            ) : (
              <Flex flexDirection="column" gap={2}>
                {error && <Alert severity="error">{error.message}</Alert>}

                <TextField
                  label={<Trans>Pool Payout Instructions</Trans>}
                  name="payoutAddress"
                  variant="filled"
                  InputProps={{
                    spellCheck: false,
                    endAdornment: (
                      <InputAdornment position="end">
                        <CopyToClipboard value={currentPayoutAddress} />
                      </InputAdornment>
                    ),
                  }}
                  fullWidth
                />

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
          <Button onClick={handleClose} color="secondary">
            <Trans>Cancel</Trans>
          </Button>
          <Button color="primary" type="submit">
            <Trans>Save</Trans>
          </Button>
        </DialogActions>
      </Form>
    </Dialog>
  );
}

PlotNFTPayoutInstructionsDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
