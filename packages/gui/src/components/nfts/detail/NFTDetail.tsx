import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { Back, Flex, LayoutDashboardSub, Loading } from '@chia/core';
import type { NFTInfo, Wallet } from '@chia/api';
import { useGetNFTWallets } from '@chia/api-react';
import { Box, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';
import NFTPreview from '../NFTPreview';
import useFetchNFTs from '../../../hooks/useFetchNFTs';
import useNFTMetadata from '../../../hooks/useNFTMetadata';
import NFTRankings from '../NFTRankings';
import NFTProperties from '../NFTProperties';
import NFTDetails from '../NFTDetails';

/* ========================================================================== */

export default function NFTDetail() {
  const { nftId } = useParams();
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );

  const nft: NFTInfo | undefined = useMemo(() => {
    if (!nfts) {
      return;
    }
    return nfts.find((nft: NFTInfo) => nft.$nftId === nftId);
  }, [nfts, nftId]);
  const { metadata, isLoading: isLoadingMetadata } = useNFTMetadata(nft);
  const isLoading = isLoadingWallets || isLoadingNFTs || isLoadingMetadata;

  if (isLoading) {
    return <Loading center />;
  }

  return (
    <LayoutDashboardSub>
      <Flex flexDirection="column" gap={2}>
        <Back variant="h5">
          {metadata?.name ?? <Trans>Title Not Available</Trans>}
        </Back>
        <Box
          border={1}
          borderColor="grey.300"
          borderRadius={4}
          overflow="hidden"
          alignItems="center"
          justifyContent="center"
          display={{ xs: 'flex', md: 'none' }}
        >
          {nft && <NFTPreview nft={nft} height="400px" fit="contain" />}
        </Box>
        <Flex gap={2} alignItems="stretch">
          <Flex
            flexGrow={1}
            border={1}
            borderColor="grey.300"
            borderRadius={4}
            overflow="hidden"
            alignItems="stretch"
            justifyContent="stretch"
            display={{ xs: 'none', md: 'flex' }}
            minHeight="500px"
          >
            {nft && <NFTPreview nft={nft} height="auto" fit="contain" />}
          </Flex>
          <Box maxWidth={{ md: '500px', lg: '600px' }} width="100%">
            <Flex flexDirection="column" gap={3}>
              <Flex flexDirection="column" gap={1}>
                <Typography variant="h6">
                  <Trans>Description</Trans>
                </Typography>

                <Typography>
                  {metadata?.description ?? <Trans>Not Available</Trans>}
                </Typography>
              </Flex>
              {metadata?.collection?.name && (
                <Flex flexDirection="column" gap={1}>
                  <Typography variant="h6">
                    <Trans>Collection</Trans>
                  </Typography>

                  <Typography>
                    {metadata?.collection?.name ?? <Trans>Not Available</Trans>}
                  </Typography>
                </Flex>
              )}
              {(nft?.seriesTotal ?? 0) > 1 && (
                <Flex flexDirection="column" gap={1}>
                  <Typography variant="h6">
                    <Trans>Edition Number</Trans>
                  </Typography>

                  <Typography>
                    <Trans>
                      {nft.seriesNumber} of {nft.seriesTotal}
                    </Trans>
                  </Typography>
                </Flex>
              )}
              <NFTProperties attributes={metadata?.attributes} />
              <NFTRankings attributes={metadata?.attributes} />

              <NFTDetails nft={nft} metadata={metadata} />
            </Flex>
          </Box>
        </Flex>
        {/*
        <Flex flexDirection="column" gap={1}>
          <Typography variant="h6">
            <Trans>Item Activity</Trans>
          </Typography>
          <Table cols={cols} rows={metadata.activity} />
        </Flex>
        */}
      </Flex>
    </LayoutDashboardSub>
  );
}
