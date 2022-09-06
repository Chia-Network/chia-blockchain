import React from 'react';
import { Trans, t } from '@lingui/macro';
import { useGetNFTInfoQuery } from '@chia/api-react';
import {
  Button,
  Flex,
  Loading,
  TooltipIcon,
  useColorModeValue,
} from '@chia/core';
import { Card, Grid, Typography } from '@mui/material';
import NFTCard from '../nfts/NFTCard';
import { launcherIdFromNFTId } from '../../util/nfts';
import { NFTContextualActionTypes } from '../nfts/NFTContextualActions';
import styled from 'styled-components';
import useViewNFTOnExplorer, {
  NFTExplorer,
} from '../../hooks/useViewNFTOnExplorer';

/* ========================================================================== */

const StyledPreviewContainer = styled(Flex)`
  width: 364px;
  border-left: ${({ theme }) =>
    `1px solid ${useColorModeValue(theme, 'border')}`};
  background-color: ${({ theme }) => theme.palette.background.default};
  padding-bottom: ${({ theme }) => theme.spacing(4)};
`;

const StyledCard = styled(Card)`
  width: 300px;
  height: 362px;
  display: flex;
  border-radius: 8px;
`;

/* ========================================================================== */

type NFTOfferPreviewProps = {
  nftId?: string;
};

export default function NFTOfferPreview(props: NFTOfferPreviewProps) {
  const { nftId } = props;
  const launcherId = launcherIdFromNFTId(nftId ?? '');
  const {
    data: nft,
    isLoading: isLoadingNFT,
    error: rawError,
  } = useGetNFTInfoQuery({ coinId: launcherId ?? '' });
  const viewOnExplorer = useViewNFTOnExplorer();
  let error = rawError?.message ?? '';

  if (error) {
    if (error.startsWith('The coin is not a NFT.')) {
      error = t`NFT identifier does not reference a valid NFT coin.`;
    }
  }

  const cardContentElem = (function () {
    if (isLoadingNFT) {
      return (
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
          <Loading center>
            <Trans>Loading NFT Info...</Trans>
          </Loading>
        </Flex>
      );
    } else if (launcherId && nft) {
      return (
        <Grid xs={12} item>
          <NFTCard
            nft={nft}
            canExpandDetails={false}
            availableActions={
              NFTContextualActionTypes.CopyNFTId |
              NFTContextualActionTypes.ViewOnExplorer |
              NFTContextualActionTypes.OpenInBrowser |
              NFTContextualActionTypes.CopyURL
            }
            isOffer
          />
        </Grid>
      );
    } else if (launcherId && error) {
      return (
        <Flex
          flexDirection="column"
          alignItems="center"
          justifyContent="center"
          flexGrow={1}
          gap={1}
          padding={3}
        >
          <Typography variant="body1" color="error">
            {error}
          </Typography>
        </Flex>
      );
    } else {
      return (
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
      );
    }
  })();

  return (
    <StyledPreviewContainer
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      gap={1}
    >
      <Flex
        flexDirection="column"
        gap={1}
        style={{
          padding: '1.5rem',
        }}
      >
        <Typography variant="subtitle1">Preview</Typography>
        <StyledCard>{cardContentElem}</StyledCard>
      </Flex>
      {nft && (
        <Flex
          flexDirection="column"
          flexGrow={1}
          alignItems="center"
          gap={2}
          style={{
            width: '100%',
            padding: '0 2rem',
          }}
        >
          <Flex
            flexDirection="row"
            alignItems="center"
            gap={0.5}
            style={{ width: '100%' }}
          >
            <Typography variant="subtitle1">Provenance</Typography>
            <TooltipIcon>
              <Trans>
                An NFT's provenance is a complete record of its ownership
                history. It provides a direct lineage that connects everyone who
                has owned the NFT, all the way back to the original artist. This
                helps to verify that the NFT is authentic.
              </Trans>
            </TooltipIcon>
          </Flex>
          <Button
            variant="outlined"
            color="primary"
            onClick={() => viewOnExplorer(nft, NFTExplorer.MintGarden)}
            style={{ width: '100%' }}
          >
            <Typography variant="caption" color="secondary">
              <Trans>Check Provenance on MintGarden</Trans>
            </Typography>
          </Button>
          <Button
            variant="outlined"
            color="primary"
            onClick={() => viewOnExplorer(nft, NFTExplorer.SkyNFT)}
            style={{ width: '100%' }}
          >
            <Typography variant="caption" color="secondary">
              <Trans>Check Provenance on SkyNFT</Trans>
            </Typography>
          </Button>
          <Button
            variant="outlined"
            color="primary"
            onClick={() => viewOnExplorer(nft, NFTExplorer.Spacescan)}
            style={{ width: '100%' }}
          >
            <Typography variant="caption" color="secondary">
              <Trans>Check Provenance on Spacescan.io</Trans>
            </Typography>
          </Button>
        </Flex>
      )}
    </StyledPreviewContainer>
  );
}
