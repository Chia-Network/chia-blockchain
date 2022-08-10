import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import type { NFTInfo } from '@chia/api';
import {
  Button,
  ButtonLoading,
  Fee,
  Form,
  Flex,
  TextField,
  chiaToMojo,
  useCurrencyCode,
  useOpenDialog,
  validAddress,
  useShowError,
} from '@chia/core';
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Typography,
} from '@mui/material';
import { useForm } from 'react-hook-form';
import { useTransferNFTMutation } from '@chia/api-react';
import NFTSummary from './NFTSummary';
import NFTTransferConfirmationDialog from './NFTTransferConfirmationDialog';

/* ========================================================================== */
/*                              NFTTransferResult                             */
/* ========================================================================== */

export type NFTTransferResult = {
  success: boolean;
  transferInfo?: {
    nftAssetId: string;
    destination: string;
    fee: string;
  };
  error?: string;
};

/* ========================================================================== */
/*                      NFT Transfer Confirmation Dialog                      */
/* ========================================================================== */

/* ========================================================================== */
/*                         NFT Transfer Action (Form)                         */
/* ========================================================================== */

type NFTTransferFormData = {
  destination: string;
  fee: string;
};

type NFTTransferActionProps = {
  nft: NFTInfo;
  destination?: string;
  onComplete?: (result?: NFTTransferResult) => void;
};

export default function NFTTransferAction(props: NFTTransferActionProps) {
  const { nft, destination = '', onComplete } = props;
  const [isLoading, setIsLoading] = useState(false);
  const [transferNFT] = useTransferNFTMutation();
  const openDialog = useOpenDialog();
  const showError = useShowError();
  const currencyCode = useCurrencyCode();
  const methods = useForm<NFTTransferFormData>({
    shouldUnregister: false,
    defaultValues: {
      destination,
      fee: '',
    },
  });

  async function handleClose() {
    if (onComplete) {
      onComplete(); // No result provided if the user cancels out of the dialog
    }
  }

  async function handleSubmit(formData: NFTTransferFormData) {
    const { destination, fee } = formData;
    const feeInMojos = chiaToMojo(fee || 0);

    try {
      if (!currencyCode) {
        throw new Error('Selected network address prefix is not defined');
      }
      validAddress(destination, [currencyCode.toLowerCase()]);
    } catch (error) {
      showError(error);
      return;
    }

    const confirmation = await openDialog(
      <NFTTransferConfirmationDialog destination={destination} fee={fee} />,
    );

    if (confirmation) {
      setIsLoading(true);

      const { error, data: response } = await transferNFT({
        walletId: nft.walletId,
        nftCoinId: nft.nftCoinId,
        launcherId: nft.launcherId,
        targetAddress: destination,
        fee: feeInMojos,
      });
      const success = response?.success ?? false;
      const errorMessage = error ?? undefined;

      setIsLoading(false);

      if (onComplete) {
        onComplete({
          success,
          transferInfo: {
            nftAssetId: nft.nftCoinId,
            destination,
            fee,
          },
          error: errorMessage,
        });
      }
    }
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex flexDirection="column" gap={3}>
        <Flex flexDirection="column" gap={1}>
          <NFTSummary launcherId={nft.launcherId} />
        </Flex>
        <TextField
          name="destination"
          variant="filled"
          color="secondary"
          fullWidth
          label={<Trans>Send to Address</Trans>}
          disabled={isLoading}
          required
        />
        <Fee
          id="filled-secondary"
          variant="filled"
          name="fee"
          color="secondary"
          label={<Trans>Fee</Trans>}
          disabled={isLoading}
        />
        <DialogActions>
          <Flex flexDirection="row" gap={3}>
            <Button
              onClick={handleClose}
              color="secondary"
              variant="outlined"
              autoFocus
            >
              <Trans>Close</Trans>
            </Button>
            <ButtonLoading
              type="submit"
              autoFocus
              color="primary"
              variant="contained"
              loading={isLoading}
            >
              <Trans>Transfer</Trans>
            </ButtonLoading>
          </Flex>
        </DialogActions>
      </Flex>
    </Form>
  );
}

/* ========================================================================== */
/*                             NFT Transfer Dialog                            */
/* ========================================================================== */

type NFTTransferDialogProps = {
  open: boolean;
  onClose: (value: any) => void;
  onComplete?: (result?: NFTTransferResult) => void;
  nft: NFTInfo;
  destination?: string;
};

export function NFTTransferDialog(props: NFTTransferDialogProps) {
  const { open, onClose, onComplete, nft, destination, ...rest } = props;

  function handleClose() {
    onClose(false);
  }

  function handleCompletion(result?: NFTTransferResult) {
    onClose(true);
    if (onComplete) {
      onComplete(result);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      aria-labelledby="nft-transfer-dialog-title"
      aria-describedby="nft-transfer-dialog-description"
      maxWidth="sm"
      fullWidth
      {...rest}
    >
      <DialogTitle id="nft-transfer-dialog-title">
        <Flex flexDirection="row" gap={1}>
          <Typography variant="h6">
            <Trans>Transfer NFT</Trans>
          </Typography>
        </Flex>
      </DialogTitle>
      <DialogContent>
        <Flex flexDirection="column" gap={3}>
          <DialogContentText id="nft-transfer-dialog-description">
            <Trans>
              Would you like to transfer the specified NFT to a new owner?
            </Trans>
          </DialogContentText>
          <NFTTransferAction
            nft={nft}
            destination={destination}
            onComplete={handleCompletion}
          />
        </Flex>
      </DialogContent>
    </Dialog>
  );
}

NFTTransferDialog.defaultProps = {
  open: false,
  onClose: () => {},
};
