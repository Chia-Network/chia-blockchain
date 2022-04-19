import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Form, TextField, useOpenDialog } from '@chia/core';
import { Button } from '@mui/material';
import { useForm } from 'react-hook-form';
import NFT from '../../types/NFT';

type NFTCreateOfferDemoFormData = {
  walletId: number;
  nftAssetId: string;
};

type NFTCreateOfferDemoProps = {
  nft?: NFT;
};

export default function NFTCreateOfferDemo(props: NFTCreateOfferDemoProps) {
  const { nft } = props;
  const openDialog = useOpenDialog();
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
    console.log(walletId);
    console.log(nftAssetId);
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
