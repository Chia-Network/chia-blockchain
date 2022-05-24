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
import { useGetNFTWallets } from '@chia/api-react';
import { Box, Grid, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';
import NFTPreview from '../NFTPreview';
import useFetchNFTs from '../../../hooks/useFetchNFTs';
import useNFTMetadata from '../../../hooks/useNFTMetadata';


export default function NFTDetail() {
  const { nftId } = useParams();
  const { wallets: nftWallets, isLoading: isLoadingWallets } = useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );

  const nft: NFTInfo | undefined = useMemo(() => {
    if (!nfts) {
      return;
    }
    return nfts.find((nft: NFTInfo) => nft.$nftId === nftId);
  }, [nfts]);

  const { metadata, isLoading: isLoadingMetadata, error } = useNFTMetadata(nft);
  const launcherId: string | undefined = nft?.launcherId;

  console.log('nft', nft);
  console.log('metadata', metadata, isLoadingMetadata, error);

  const isLoading = isLoadingWallets || isLoadingNFTs || isLoadingMetadata;

  const details = useMemo(() => {
    if (!nft) {
      return [];
    }

    const { dataUris = []} = nft;

    const rows = [{
      key: 'id',
      label: <Trans>Launcher ID</Trans>,
      value: (
        <Truncate tooltip copyToClipboard>
          {nft.launcherId}
        </Truncate>
      ),
    },
    // {
    //   key: 'tokenStandard',
    //   label: <Trans>Token Standard</Trans>,
    //   value: nft.version,
    // },
    nft.dataHash && {
      key: 'dataHash',
      label: <Trans>Data Hash</Trans>,
      value: <Truncate tooltip copyToClipboard>{nft.dataHash}</Truncate>,
    }].filter(Boolean);

    if (dataUris?.length) {
      dataUris.forEach((uri, index) => {
        rows.push({
          key: `dataUri-${index}`,
          label: <Trans>Data URL {index + 1}</Trans>,
          value: uri,
        });
      });
    }

    if (nft.licenseHash) {
      rows.push({
        key: 'licenseHash',
        label: <Trans>License Hash</Trans>,
        value: <Truncate>{nft.licenseHash}</Truncate>,
      });
    }

    if (nft?.licenseUris?.length) {
      nft?.licenseUris.forEach((uri, index) => {
        rows.push({
          key: `licenseUris-${index}`,
          label: <Trans>License URL {index + 1}</Trans>,
          value: uri,
        });
      });
    }

    return rows;
  }, [metadata, nft]);

  if (isLoading) {
    return <Loading center />;
  }

  const attributes = metadata?.attributes ?? [];

  return (
    <Flex flexDirection="column" gap={2}>
      <Flex backgroundColor="white" justifyContent="center" py={8}>

        <Box
          // border={1}
          // borderColor="grey.300"
          // borderRadius={4}
          overflow="hidden"
          alignItems="center"
          justifyContent="center"
          maxWidth="800px"
          alignSelf="center"
          width="100%"
          position="relative"
        >
          {nft && (
            <NFTPreview nft={nft} width="100%" height="400px" fit="contain" />
          )}
          <Box position="absolute" left={1} top={1}>
            <Back variant="h5"></Back>
          </Box>
        </Box>
      </Flex>
    <LayoutDashboardSub>
      <Flex flexDirection="column" gap={2} maxWidth="1200px" alignSelf="center">


        <Typography variant="h5">{metadata?.name ?? <Trans>Title Not Available</Trans>}</Typography>
        <Flex flexDirection="column" gap={3}>
          <Flex flexDirection="column" gap={1}>
            <Typography variant="h6">
              <Trans>Description</Trans>
            </Typography>

            <Typography>{metadata?.description ?? <Trans>Not Available</Trans>}</Typography>
          </Flex>
          {!!attributes.length && (
            <Flex flexDirection="column" gap={1}>
            <Typography variant="h6">
              <Trans>Properties</Trans>
            </Typography>

            <Grid spacing={2} container>
              {attributes.map((attribute, index) => (
                <Grid xs={12} sm={6} md={4} lg={3} key={`${attribute?.name}-${index}`} item>
                  <Box border={1} borderRadius={1} borderColor="black" p={2}>
                    <Typography variant="body1" noWrap>
                      {attribute?.name}
                    </Typography>
                    <Typography variant="h6" noWrap>
                      {attribute?.value}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </Flex>
          )}
          <Flex flexDirection="column" gap={1}>
            <Typography variant="h6">
              <Trans>Details</Trans>
            </Typography>

            <CardKeyValue rows={details} hideDivider />
          </Flex>
        </Flex>
        {/**
        <Flex flexDirection="column" gap={1}>
          <Typography variant="h6">
            <Trans>Item Activity</Trans>
          </Typography>
          <Table cols={cols} rows={metadata.activity} />
        </Flex>
        */}
      </Flex>
    </LayoutDashboardSub>
    </Flex>
  );
}
