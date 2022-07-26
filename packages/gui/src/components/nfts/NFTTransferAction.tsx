import React, { useState } from 'react';
import { Plural, Trans } from '@lingui/macro';
import styled from 'styled-components';
import type { NFTInfo } from '@chia/api';
import {
  Button,
  ButtonLoading,
  ConfirmDialog,
  Fee,
  Form,
  FormatLargeNumber,
  Flex,
  TextField,
  TooltipIcon,
  chiaToMojo,
  useCurrencyCode,
  useOpenDialog,
  validAddress,
  useShowError,
} from '@chia/core';
import {
  Box,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Typography,
} from '@mui/material';
import { useForm } from 'react-hook-form';
import { useTransferNFTMutation } from '@chia/api-react';
import NFTSummary from './NFTSummary';

/* ========================================================================== */
/*                                   Styles                                   */
/* ========================================================================== */

const StyledTitle = styled(Box)`
  font-size: 0.625rem;
  color: rgba(255, 255, 255, 0.7);
`;

const StyledValue = styled(Box)`
  word-break: break-all;
`;

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

type NFTTransferConfirmationDialogProps = NFTTransferFormData & {
  open: boolean; // For use in openDialog()
};

function NFTTransferConfirmationDialog(
  props: NFTTransferConfirmationDialogProps,
) {
  const { destination, fee, ...rest } = props;
  const feeInMojos = chiaToMojo(fee || 0);
  const currencyCode = useCurrencyCode();

  return (
    <ConfirmDialog
      title={<Trans>Confirm NFT Transfer</Trans>}
      confirmTitle={<Trans>Transfer</Trans>}
      confirmColor="secondary"
      cancelTitle={<Trans>Cancel</Trans>}
      {...rest}
    >
      <Flex flexDirection="column" gap={3}>
        <Typography variant="body1">
          <Trans>
            Once you initiate this transfer, you will not be able to cancel the
            transaction. Are you sure you want to transfer the NFT?
          </Trans>
        </Typography>
        <Divider />
        <Flex flexDirection="column" gap={1}>
          <Flex flexDirection="row" gap={1}>
            <Flex flexShrink={0}>
              <Typography variant="body1">
                <Trans>Destination:</Trans>
              </Typography>
            </Flex>
            <Flex
              flexDirection="row"
              alignItems="center"
              gap={1}
              sx={{ overflow: 'hidden' }}
            >
              <Typography noWrap variant="body1">
                {destination}
              </Typography>
              <TooltipIcon interactive>
                <Flex flexDirection="column" gap={1}>
                  <StyledTitle>
                    <Trans>Destination</Trans>
                  </StyledTitle>
                  <StyledValue>
                    <Typography variant="caption">{destination}</Typography>
                  </StyledValue>
                </Flex>
              </TooltipIcon>
            </Flex>
          </Flex>
          <Flex flexDirection="row" gap={1}>
            <Typography variant="body1">Fee:</Typography>
            <Typography variant="body1">
              {fee || '0'} {currencyCode}
            </Typography>
            {feeInMojos > 0 && (
              <>
                (
                <FormatLargeNumber value={feeInMojos} />
                <Box>
                  <Plural
                    value={feeInMojos.toNumber()}
                    one="mojo"
                    other="mojos"
                  />
                </Box>
                )
              </>
            )}
          </Flex>
        </Flex>
      </Flex>
    </ConfirmDialog>
  );
}

NFTTransferConfirmationDialog.defaultProps = {
  open: false,
};

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
