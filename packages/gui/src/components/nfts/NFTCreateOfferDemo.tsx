import React from 'react';
import { Trans } from '@lingui/macro';
import type { NFT } from '@chia/api';
import { Flex, Form, TextField } from '@chia/core';
import {
  Button,
  Dialog,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';

/* ========================================================================== */
/*                                 Demo Dialog                                */
/* ========================================================================== */

type NFTCreateOfferDemoDialogProps = {
  nft: NFT;
  referrerPath?: string;
  onClose: () => void;
  open: boolean;
};

export default function NFTCreateOfferDemoDialog(
  props: NFTCreateOfferDemoDialogProps,
) {
  const { nft, referrerPath, onClose, open } = props;

  return (
    <Dialog
      onClose={onClose}
      open={open}
      aria-labelledby="nft-create-offer-dialog-title"
      aria-describedby="nft-create-offer-dialog-description"
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle id="nft-create-offer-dialog-title">
        <Typography variant="h6">
          <Trans>NFT Create Offer Demo</Trans>
        </Typography>
      </DialogTitle>
      <DialogContent>
        <Flex justifyContent="center">
          <NFTCreateOfferDemo
            nft={nft}
            referrerPath={referrerPath}
            onComplete={onClose}
          />
        </Flex>
      </DialogContent>
    </Dialog>
  );
}

NFTCreateOfferDemoDialog.defaultProps = {
  referrerPath: undefined,
  onClose: () => {},
  open: false,
};

/* ========================================================================== */
/*                             Demo Dialog Content                            */
/* ========================================================================== */

type NFTCreateOfferDemoFormData = {
  walletId: number;
  nftAssetId: string;
};

type NFTCreateOfferDemoProps = {
  nft?: NFT;
  referrerPath?: string;
  onComplete: () => void;
};

export function NFTCreateOfferDemo(props: NFTCreateOfferDemoProps) {
  const { nft, referrerPath, onComplete } = props;
  const navigate = useNavigate();
  const methods = useForm<NFTCreateOfferDemoFormData>({
    shouldUnregister: false,
    defaultValues: {
      walletId: nft?.walletId ?? 0,
      nftAssetId: nft?.id ?? '',
    },
  });

  async function handleInitiateOfferCreation(
    formData: NFTCreateOfferDemoFormData,
  ) {
    const { walletId, nftAssetId } = formData;

    console.log('Create offer');
    onComplete();
    console.log(walletId);
    console.log(nftAssetId);
    navigate('/dashboard/offers/create-with-nft', {
      state: { nft, referrerPath },
    });
  }

  return (
    <Flex flexDirection="row" flexGrow={1} gap={3} style={{ padding: '1rem' }}>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Form methods={methods} onSubmit={handleInitiateOfferCreation}>
          <Flex flexDirection="column" gap={3}>
            <TextField
              name="walletId"
              variant="outlined"
              label="Wallet ID"
              required
              fullWidth
            />
            <TextField
              name="nftAssetId"
              variant="outlined"
              label="NFT Coin Info"
              required
              fullWidth
            />
            <Flex justifyContent="flex-end">
              <Button type="submit" variant="contained" color="primary">
                <Trans>Create Offer</Trans>
              </Button>
            </Flex>
          </Flex>
        </Form>
      </Flex>
    </Flex>
  );
}

NFTCreateOfferDemo.defaultProps = {
  nft: undefined,
  referrerPath: undefined,
  onComplete: () => {},
};
