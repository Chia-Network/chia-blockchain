import React from 'react';
import { Trans } from '@lingui/macro';
import type { NFTInfo } from '@chia/api';
import { useGetNFTInfoQuery } from '@chia/api-react';
import { Flex } from '@chia/core';
import { Box, Typography } from '@mui/material';
import NFTCard from '../nfts/NFTCard';
import { isValidNFTId, launcherIdFromNFTId } from '../../util/nfts';
import useGetNFTInfoById from '../../hooks/useGetNFTInfoById';

/* ========================================================================== */

type NFTOfferPreviewProps = {
  nftId?: string;
  // nft?: NFTInfo;
};

export default function NFTOfferPreview(props: NFTOfferPreviewProps) {
  const { /*nft,*/ nftId } = props;
  const borderStyle = isValidNFTId(nftId ?? '')
    ? 'none' //'2px solid #E0E0E0'
    : '2px dashed #E0E0E0';
  // TODO: Load NFT info
  const launcherId = launcherIdFromNFTId(nftId ?? '');
  const {
    data: nft,
    isLoading,
    error,
  } = useGetNFTInfoQuery({ coinId: launcherId });
  // const nft = data ? { ...data, id: nftId } : undefined;
  // const nft = useGetNFTInfoById(nftId);

  return (
    <Flex
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      style={{
        width: '328px',
        minHeight: '576px',
        borderLeft: '1px solid #E0E0E0',
      }}
      gap={1}
    >
      <Flex
        flexDirection="column"
        flexGrow={1}
        gap={1}
        style={{
          padding: '1.5rem',
        }}
      >
        <Typography variant="subtitle1">Preview</Typography>
        <Box
          sx={{
            width: '264px',
            minHeight: '456px',
            boxSizing: 'border-box',
            border: `${borderStyle}`,
            borderRadius: '4px',
            display: 'flex',
            overflow: 'hidden',
          }}
        >
          {nft !== undefined ? (
            <NFTCard nft={nft} />
          ) : (
            <Flex
              flexDirection="column"
              alignItems="center"
              justifyContent="center"
              flexGrow={1}
              gap={1}
              style={{
                wordBreak: 'break-all',
              }}
            >
              <Typography variant="h6">
                <Trans>NFT not specified</Trans>
              </Typography>
            </Flex>
          )}
        </Box>
      </Flex>
    </Flex>
  );
}
