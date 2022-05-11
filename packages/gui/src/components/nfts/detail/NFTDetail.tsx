import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import moment from 'moment';
import {
  Back,
  Flex,
  LayoutDashboardSub,
  Loading,
  Table,
  mojoToChia,
  FormatLargeNumber,
  CardKeyValue,
  Truncate,
} from '@chia/core';
import type { NFTInfo } from '@chia/api';
import { useGetNFTWallets, useNFTMetadata } from '@chia/api-react';
import { Box, Grid, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';
import NFTPreview from '../NFTPreview';
import useFetchNFTs from '../../../hooks/useFetchNFTs';

const cols = [
  {
    field: ({ date }) => (
      <Typography color="textSecondary" variant="body2">
        {moment(date).format('LLL')}
      </Typography>
    ),
    title: <Trans>Date</Trans>,
  },
  {
    field: 'from',
    title: <Trans>From</Trans>,
  },
  {
    field: 'to',
    title: <Trans>To</Trans>,
  },
  {
    field: ({ amount }) => (
      <strong>
        <FormatLargeNumber value={mojoToChia(amount)} />
        &nbsp; XCH
      </strong>
    ),
    title: <Trans>Amount</Trans>,
  },
];

export default function NFTDetail() {
  const { nftId: launcherId } = useParams();
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );
  const { metadata: fakeMetadata, isLoading } = useNFTMetadata({
    id: launcherId,
  });

  const nft = useMemo(() => {
    if (!nfts) {
      return;
    }
    return nfts.find((nft: NFTInfo) => nft.launcherId === launcherId);
  }, [nfts]);

  const metadata = { ...fakeMetadata, ...nft };

  if (isLoading) {
    return <Loading center />;
  }

  const details = [
    {
      key: 'id',
      label: <Trans>Launcher ID</Trans>,
      value: <Truncate tooltip copyToClipboard>{launcherId}</Truncate>,
    },
    {
      key: 'contract',
      label: <Trans>Contract Address</Trans>,
      value: <Truncate tooltip copyToClipboard>{metadata.contractAddress}</Truncate>,
    },
    {
      key: 'tokenStandard',
      label: <Trans>Token Standard</Trans>,
      value: metadata.standard,
    },
    {
      key: 'belongs',
      label: <Trans>Belongs To</Trans>,
      value: metadata.owner,
    },
    {
      key: 'dataHash',
      label: <Trans>Data Hash</Trans>,
      value: <Truncate tooltip copyToClipboard>{metadata.hash}</Truncate>,
    },
  ];

  return (
    <LayoutDashboardSub>
      <Flex flexDirection="column" gap={2}>
        <Back variant="h5">{metadata.name}</Back>
        <Box
          border={1}
          borderColor="grey.300"
          borderRadius={4}
          overflow="hidden"
          alignItems="center"
          justifyContent="center"
          display={{ sm: 'flex', md: 'none' }}
        >
          {nft && <NFTPreview nft={nft} height="auto" />}
        </Box>
        <Flex gap={2} alignItems="stretch">
          <Box
            flexGrow={1}
            border={1}
            borderColor="grey.300"
            borderRadius={4}
            height="100%"
            overflow="hidden"
            alignItems="center"
            justifyContent="center"
            display={{ sm: 'none', md: 'flex' }}
          >
            {nft && <NFTPreview nft={nft} height="auto" />}
          </Box>
          <Box maxWidth={{ md: '500px', lg: '600px' }}>
            <Flex flexDirection="column" gap={3}>
              <Flex flexDirection="column" gap={1}>
                <Typography variant="h6">
                  <Trans>Description</Trans>
                </Typography>

                <Typography>{metadata.description}</Typography>
              </Flex>
              <Flex flexDirection="column" gap={1}>
                <Typography variant="h6">
                  <Trans>Details</Trans>
                </Typography>

                <CardKeyValue rows={details} hideDivider />
              </Flex>
            </Flex>
          </Box>
        </Flex>
        <Flex flexDirection="column" gap={1}>
          <Typography variant="h6">
            <Trans>Item Activity</Trans>
          </Typography>
          <Table cols={cols} rows={metadata.activity} />
        </Flex>
      </Flex>
    </LayoutDashboardSub>
  );
}
