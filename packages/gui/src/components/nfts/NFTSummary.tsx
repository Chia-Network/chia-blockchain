import React, { useMemo } from 'react';
import { t, Trans } from '@lingui/macro';
import type { NFTAttribute } from '@chia/api';
import { useGetNFTInfoQuery } from '@chia/api-react';
import {
  CopyToClipboard,
  Flex,
  Loading,
  TooltipIcon,
  truncateValue,
} from '@chia/core';
import { Box, Card, CardContent, Typography } from '@mui/material';
import { useTheme } from '@mui/material/styles';
import useNFTMetadata from '../../hooks/useNFTMetadata';
import isRankingAttribute from '../../util/isRankingAttribute';
import { launcherIdToNFTId } from '../../util/nfts';
import NFTPreview from '../nfts/NFTPreview';
import { NFTProperty } from '../nfts/NFTProperties';
import { NFTRanking } from '../nfts/NFTRankings';
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

export type NFTSummaryProps = {
  launcherId: string;
};

export default function NFTSummary(props: NFTSummaryProps) {
  const { launcherId } = props;
  const nftId = launcherIdToNFTId(launcherId);
  const theme = useTheme();
  const bottomPadding = `${theme.spacing(2)}`; // logic borrowed from Flex's gap computation
  const { data: nft, isLoading: isLoadingNFT } = useGetNFTInfoQuery({
    coinId: launcherId,
  });
  const { metadata, isLoading: isLoadingMetadata } = useNFTMetadata(nft);

  const [properties, rankings] = useMemo(() => {
    if (!nft) {
      return [[], []];
    }

    const properties: React.ReactElement[] = [];
    const rankings: React.ReactElement[] = [];

    const collectionNameProperty = metadata?.collection_name ? (
      <NFTProperty
        attribute={{ name: t`Collection`, value: metadata.collection_name }}
        size="small"
        color="secondary"
      />
    ) : null;

    const editionProperty =
      nft?.seriesNumber && nft?.seriesTotal > 1 ? (
        <NFTProperty
          attribute={{
            name: t`Edition #`,
            value: `${nft.seriesNumber}/${nft.seriesTotal}`,
          }}
          size="small"
          color="secondary"
        />
      ) : null;

    if (collectionNameProperty) {
      properties.push(collectionNameProperty);
    }

    if (editionProperty) {
      properties.push(editionProperty);
    }

    metadata
      ?.attributes
      ?.filter((attribute: NFTAttribute) => !isRankingAttribute(attribute))
      .forEach((attribute: NFTAttribute) =>
        properties.push(
          <NFTProperty attribute={attribute} size="small" color="secondary" />,
        ),
      );

    metadata
      ?.attributes
      ?.filter((attribute: NFTAttribute) => isRankingAttribute(attribute))
      .forEach((attribute: NFTAttribute) =>
        rankings.push(
          <NFTRanking
            attribute={attribute}
            size="small"
            color="secondary"
            progressColor="secondary"
          />,
        ),
      );

    return [properties, rankings];
  }, [nft, metadata]);

  const havePropertiesOrRankings = properties.length > 0 || rankings.length > 0;

  if (isLoadingNFT || isLoadingMetadata || !nft) {
    return (
      <Flex flexGrow={1} flexDirection="column" alignItems="center" gap={1}>
        <Typography variant="subtitle1">
          <Trans>Loading NFT</Trans>
        </Typography>
        <Loading center />
      </Flex>
    );
  }

  const NFTIDComponent = function (props: any) {
    const { ...rest } = props;
    const truncatedNftId = truncateValue(nftId, {});

    return (
      <Flex flexDirection="row" alignItems="center" gap={1} {...rest}>
        <Typography variant="body2">{truncatedNftId}</Typography>
        <TooltipIcon interactive>
          <Flex flexDirection="column" gap={1}>
            <Flex flexDirection="column" gap={0}>
              <Flex>
                <Box flexGrow={1}>
                  <StyledTitle>NFT ID</StyledTitle>
                </Box>
              </Flex>
              <Flex alignItems="center" gap={1}>
                <StyledValue>{nftId}</StyledValue>
                <CopyToClipboard value={nftId} fontSize="small" invertColor />
              </Flex>
            </Flex>
            <Flex flexDirection="column" gap={0}>
              <Flex>
                <Box flexGrow={1}>
                  <StyledTitle>Launcher ID</StyledTitle>
                </Box>
              </Flex>
              <Flex alignItems="center" gap={1}>
                <StyledValue>{launcherId}</StyledValue>
                <CopyToClipboard
                  value={launcherId}
                  fontSize="small"
                  invertColor
                />
              </Flex>
            </Flex>
          </Flex>
        </TooltipIcon>
      </Flex>
    );
  };

  return (
    <Card>
      <CardContent style={{ paddingBottom: `${bottomPadding}` }}>
        <Flex flexDirection="column" gap={2}>
          <Flex flexDirection="row" gap={2}>
            <Box
              borderRadius={2}
              overflow="hidden"
              alignItems="center"
              justifyContent="center"
              width="80px"
              minWidth="80px"
              height="80px"
            >
              <NFTPreview nft={nft} height={80} />
            </Box>
            <Flex
              flexDirection="column"
              gap={0}
              style={{
                overflow: 'hidden',
                wordBreak: 'break-word',
                textOverflow: 'ellipsis',
              }}
            >
              <Typography variant="h6" fontWeight="bold" noWrap>
                {metadata?.name ?? <Trans>Title Not Available</Trans>}
              </Typography>
              {metadata?.description && (
                <Typography variant="caption" noWrap>
                  {metadata.description}
                </Typography>
              )}
              <NFTIDComponent style={{ paddingTop: '0.5rem' }} />
            </Flex>
          </Flex>
          {havePropertiesOrRankings && (
            <Flex flexDirection="column" gap={2} style={{ overflowX: 'auto' }}>
              {properties.length > 0 && (
                <Flex flexDirection="row" gap={1}>
                  {properties?.map((property, index) => (
                    <React.Fragment key={index}>{property}</React.Fragment>
                  ))}
                </Flex>
              )}
              {rankings.length > 0 && (
                <Flex flexDirection="row" gap={1}>
                  {rankings?.map((ranking, index) => (
                    <React.Fragment key={index}>{ranking}</React.Fragment>
                  ))}
                </Flex>
              )}
            </Flex>
          )}
        </Flex>
      </CardContent>
    </Card>
  );
}
