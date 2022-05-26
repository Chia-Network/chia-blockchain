import React from 'react';
import { Trans } from '@lingui/macro';
import { useGetNFTInfoQuery } from '@chia/api-react';
import { Flex } from '@chia/core';
import { Box, Card, Typography } from '@mui/material';
import NFTCard from '../nfts/NFTCard';
import { launcherIdFromNFTId } from '../../util/nfts';
import { NFTContextualActionTypes } from '../nfts/NFTContextualActions';
import styled from 'styled-components';

/* ========================================================================== */

const StyledPreviewContainer = styled(Flex)`
  width: 328px;
  // min-height: 576px;
  border-left: 1px solid ${({ theme }) => theme.palette.border.main};
`;

const StyledEmptyPreview = styled(Box)`
  width: 264px;
  height: 406px;
  box-sizing: border-box;
  border: none;
  border-radius: 4px;
  display: flex;
  overflow: hidden;
`;

const StyledCard = styled(Card)`
  width: 264px;
  height: 406px;
  display: flex;
`;

/* ========================================================================== */

type NFTOfferPreviewProps = {
  nftId?: string;
};

export default function NFTOfferPreview(props: NFTOfferPreviewProps) {
  const { nftId } = props;
  const launcherId = launcherIdFromNFTId(nftId ?? '');
  const borderStyle = launcherId
    ? 'none' //'2px solid #E0E0E0'
    : '2px dashed #E0E0E0';
  const {
    data: nft,
    isLoading,
    error,
  } = useGetNFTInfoQuery({ coinId: launcherId });

  return (
    <StyledPreviewContainer
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
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
        <StyledCard>
          {launcherId && nft ? (
            <NFTCard
              nft={nft}
              canExpandDetails={false}
              availableActions={NFTContextualActionTypes.None}
            />
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
        </StyledCard>
      </Flex>
    </StyledPreviewContainer>
  );
}
