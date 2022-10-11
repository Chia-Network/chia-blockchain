import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Loading } from '@chia/core';
import { useGetNFTInfoQuery } from '@chia/api-react';
import { useWatch } from 'react-hook-form';
import { Grid, Typography, Card } from '@mui/material';
import NFTCard from '../nfts/NFTCard';
import { launcherIdFromNFTId } from '../../util/nfts';
import { NFTContextualActionTypes } from '../nfts/NFTContextualActions';
import OfferBuilderValue from './OfferBuilderValue';
import OfferBuilderNFTProvenance from './OfferBuilderNFTProvenance';
import OfferBuilderNFTRoyalties from './OfferBuilderNFTRoyalties';

function PreviewCard(props) {
  const { children } = props;
  return (
    <Card sx={{ minHeight: 362 }} variant="outlined">
      <Flex
        flexDirection="column"
        alignItems="center"
        justifyContent="center"
        flexGrow={1}
        gap={1}
        padding={3}
      >
        {children}
      </Flex>
    </Card>
  );
}

export type OfferBuilderNFTProps = {
  name: string;
  onRemove?: () => void;
  provenance?: boolean;
  showRoyalties?: boolean;
};

export default function OfferBuilderNFT(props: OfferBuilderNFTProps) {
  const { name, provenance = false, showRoyalties = false, onRemove } = props;

  const fieldName = `${name}.nftId`;
  const value = useWatch({
    name: fieldName,
  });

  const launcherId = launcherIdFromNFTId(value ?? '');

  const {
    data: nft,
    isLoading: isLoadingNFT,
    error,
  } = useGetNFTInfoQuery({
    coinId: launcherId ?? '',
  });

  const hasNFT = launcherId && nft && !isLoadingNFT;

  return (
    <Flex flexDirection="column" gap={2}>
      <OfferBuilderValue
        name={fieldName}
        type="text"
        label={<Trans>NFT ID</Trans>}
        onRemove={onRemove}
      />

      {value && (
        <Flex flexDirection="column" gap={2}>
          <Typography variant="body2" color="textSecondary">
            <Trans>Preview</Trans>
          </Typography>
          <Grid spacing={3} container>
            <Grid xs={12} md={6} item>
              {!launcherId ? (
                <PreviewCard>
                  <Typography>
                    <Trans>NFT not specified</Trans>
                  </Typography>
                </PreviewCard>
              ) : isLoadingNFT ? (
                <PreviewCard>
                  <Loading />
                </PreviewCard>
              ) : error ? (
                <PreviewCard>
                  <Typography variant="body1" color="error">
                    {error.message}
                  </Typography>
                </PreviewCard>
              ) : nft ? (
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
              ) : (
                <PreviewCard>
                  <Typography>
                    <Trans>NFT not specified</Trans>
                  </Typography>
                </PreviewCard>
              )}
            </Grid>
            <Grid xs={12} md={6} item>
              {provenance && hasNFT && <OfferBuilderNFTProvenance nft={nft} />}
              {showRoyalties && hasNFT && (
                <OfferBuilderNFTRoyalties nft={nft} />
              )}
            </Grid>
          </Grid>
        </Flex>
      )}
    </Flex>
  );
}
