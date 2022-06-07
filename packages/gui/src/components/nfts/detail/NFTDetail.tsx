import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import {
  Back,
  Flex,
  LayoutDashboardSub,
  Loading,
  CardKeyValue,
  CopyToClipboard,
  Tooltip,
  Truncate,
  truncateValue,
} from '@chia/core';
import type { NFTInfo } from '@chia/api';
import { useGetNFTWallets } from '@chia/api-react';
import { Box, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';
import NFTPreview from '../NFTPreview';
import useFetchNFTs from '../../../hooks/useFetchNFTs';
import useNFTMetadata from '../../../hooks/useNFTMetadata';
import { stripHexPrefix } from '../../../util/utils';
import { didToDIDId } from '../../../util/dids';
import { convertRoyaltyToPercentage } from '../../../util/nfts';
import NFTRankings from '../NFTRankings';
import NFTProperties from '../NFTProperties';
import styled from 'styled-components';

/* ========================================================================== */

const StyledTitle = styled(Box)`
  font-size: 0.625rem;
  color: rgba(255, 255, 255, 0.7);
`;

const StyledValue = styled(Box)`
  word-break: break-all;
`;

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
  }, [nfts]);

  console.log('nft info:');
  console.log(nft);

  const { metadata, isLoading: isLoadingMetadata } = useNFTMetadata(nft);

  console.log('metadata:');
  console.log(metadata);

  const isLoading = isLoadingWallets || isLoadingNFTs || isLoadingMetadata;

  const details = useMemo(() => {
    if (!nft) {
      return [];
    }

    const { dataUris = [] } = nft;

    const rows = [
      {
        key: 'nftId',
        label: <Trans>NFT ID</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.$nftId}
          </Truncate>
        ),
      },
      {
        key: 'id',
        label: <Trans>Launcher ID</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {stripHexPrefix(nft.launcherId)}
          </Truncate>
        ),
      },
    ].filter(Boolean);

    if (nft.ownerDid) {
      const hexDIDId = stripHexPrefix(nft.ownerDid);
      const didId = didToDIDId(hexDIDId);
      const truncatedDID = truncateValue(didId, {});

      rows.push({
        key: 'ownerDid',
        label: <Trans>Owner DID</Trans>,
        value: (
          <Tooltip
            title={
              <Flex flexDirection="column" gap={1}>
                <Flex flexDirection="column" gap={0}>
                  <Flex>
                    <Box flexGrow={1}>
                      <StyledTitle>DID ID</StyledTitle>
                    </Box>
                  </Flex>
                  <Flex alignItems="center" gap={1}>
                    <StyledValue>{didId}</StyledValue>
                    <CopyToClipboard value={didId} fontSize="small" />
                  </Flex>
                </Flex>
                <Flex flexDirection="column" gap={0}>
                  <Flex>
                    <Box flexGrow={1}>
                      <StyledTitle>DID ID (Hex)</StyledTitle>
                    </Box>
                  </Flex>
                  <Flex alignItems="center" gap={1}>
                    <StyledValue>{hexDIDId}</StyledValue>
                    <CopyToClipboard value={hexDIDId} fontSize="small" />
                  </Flex>
                </Flex>
              </Flex>
            }
          >
            <Typography variant="body2">{truncatedDID}</Typography>
          </Tooltip>
        ),
      });
    }

    if (nft.ownerPubkey) {
      rows.push({
        key: 'ownerPubkey',
        label: <Trans>Owner Public Key</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {stripHexPrefix(nft.ownerPubkey)}
          </Truncate>
        ),
      });
    }

    if (nft.royaltyPercentage) {
      rows.push({
        key: 'royaltyPercentage',
        label: <Trans>Royalty Percentage</Trans>,
        value: <>{`${convertRoyaltyToPercentage(nft.royaltyPercentage)}%`}</>,
      });
    }

    if (nft.mintHeight) {
      rows.push({
        key: 'mintHeight',
        label: <Trans>Minted at Block Height</Trans>,
        value: nft.mintHeight,
      });
    }

    if (dataUris?.length) {
      dataUris.forEach((uri, index) => {
        rows.push({
          key: `dataUri-${index}`,
          label: <Trans>Data URL {index + 1}</Trans>,
          value: (
            <Tooltip title={uri} copyToClipboard>
              <Typography variant="body2">{uri}</Typography>
            </Tooltip>
          ),
        });
      });
    }

    if (nft.dataHash) {
      rows.push({
        key: 'dataHash',
        label: <Trans>Data Hash</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.dataHash}
          </Truncate>
        ),
      });
    }

    if (nft?.metadataUris?.length) {
      nft?.metadataUris.forEach((uri, index) => {
        rows.push({
          key: `metadataUris-${index}`,
          label: <Trans>Metadata URL {index + 1}</Trans>,
          value: (
            <Tooltip title={uri} copyToClipboard>
              <Typography variant="body2">{uri}</Typography>
            </Tooltip>
          ),
        });
      });
    }

    if (nft.metadataHash) {
      rows.push({
        key: 'metadataHash',
        label: <Trans>Metadata Hash</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.metadataHash}
          </Truncate>
        ),
      });
    }

    if (nft?.licenseUris?.length) {
      nft?.licenseUris.forEach((uri, index) => {
        rows.push({
          key: `licenseUris-${index}`,
          label: <Trans>License URL {index + 1}</Trans>,
          value: (
            <Tooltip title={uri} copyToClipboard>
              <Typography variant="body2">{uri}</Typography>
            </Tooltip>
          ),
        });
      });
    }

    if (nft.licenseHash) {
      rows.push({
        key: 'licenseHash',
        label: <Trans>License Hash</Trans>,
        value: (
          <Truncate ValueProps={{ variant: 'body2' }} tooltip copyToClipboard>
            {nft.licenseHash}
          </Truncate>
        ),
      });
    }

    return rows;
  }, [metadata, nft]);

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
                    <Trans>Series Number</Trans>
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
              <Flex flexDirection="column" gap={1}>
                <Typography variant="h6">
                  <Trans>Details</Trans>
                </Typography>

                <CardKeyValue rows={details} hideDivider />
              </Flex>
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
