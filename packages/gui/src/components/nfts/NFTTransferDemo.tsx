import React from 'react';
import { Trans } from '@lingui/macro';
import type { NFTInfo } from '@chia/api';
import { AlertDialog, Flex, Form, TextField, useOpenDialog } from '@chia/core';
import { Button } from '@mui/material';
import { useForm } from 'react-hook-form';
import { NFTTransferDialog, NFTTransferResult } from './NFTTransferAction';

type NFTTransferDemoFormData = {
  walletId: number;
  nftAssetId: string;
  destination?: string;
};

type NFTTransferDemoProps = {
  nft?: NFTInfo;
};

export default function NFTTransferDemo(props: NFTTransferDemoProps) {
  const { nft } = props;
  const openDialog = useOpenDialog();
  const methods = useForm<NFTTransferDemoFormData>({
    shouldUnregister: false,
    defaultValues: {
      walletId: nft?.walletId ?? 0,
      nftAssetId: nft?.nftCoinId ?? '',
      destination: '',
    },
  });

  function handleComplete(result?: NFTTransferResult) {
    if (result) {
      if (result.success) {
        openDialog(
          <AlertDialog title={<Trans>NFT Transfer Complete</Trans>}>
            <Trans>
              The NFT transfer transaction has been successfully submitted to
              the blockchain.
            </Trans>
          </AlertDialog>,
        );
      } else {
        const error = result.error || 'Unknown error';
        openDialog(
          <AlertDialog title={<Trans>NFT Transfer Failed</Trans>}>
            <Trans>The NFT transfer failed: {error}</Trans>
          </AlertDialog>,
        );
      }
    }
  }

  async function handleInitiateTransfer(formData: NFTTransferDemoFormData) {
    const { walletId, nftAssetId, destination } = formData;
    const nftToTransfer = {
      ...(nft ?? { walletId: 0, launcherId: '', name: '', description: '' }),
      walletId,
      nftCoinId: nftAssetId,
    };

    await openDialog(
      <NFTTransferDialog nft={nftToTransfer} onComplete={handleComplete} />,
    );
  }

  return (
    <Flex flexDirection="row" flexGrow={1} gap={3} style={{ padding: '1rem' }}>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Form methods={methods} onSubmit={handleInitiateTransfer}>
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
              label="NFT Coin ID"
              required
              fullWidth
            />
            <TextField
              name="destination"
              variant="outlined"
              label="Destination Address (optional)"
              fullWidth
            />
            <Flex justifyContent="flex-end">
              <Button type="submit" variant="contained" color="primary">
                <Trans>Transfer NFT</Trans>
              </Button>
            </Flex>
          </Flex>
        </Form>
      </Flex>
    </Flex>
  );
}
