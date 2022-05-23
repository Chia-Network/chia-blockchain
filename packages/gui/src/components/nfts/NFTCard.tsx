import React, { useRef } from 'react';
import { useNFTMetadata } from '@chia/api-react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Card,
  CardActionArea,
  CardContent,
  Typography,
  Radio,
} from '@mui/material';
import {
  CopyToClipboard,
  Flex,
  Loading,
  Tooltip,
  Truncate,
  mojoToChiaLocaleString,
  useCurrencyCode,
} from '@chia/core';
import styled from 'styled-components';
import NFTPreview from './NFTPreview';
import { type NFTInfo } from '@chia/api';
import useIntersectionObserver from '../../hooks/useIntersectionObserver';

const StyledCardFooter = styled(CardContent)`
  background-color: ${({ theme }) => theme.palette.action.hover};
`;

export type NFTCardProps = {
  nft: NFTInfo;
  onSelect?: (selected: boolean) => void;
  selected?: boolean;
};

export default function NFTCard(props: NFTCardProps) {
  const { nft, onSelect, selected } = props;
  const nftId = nft.$nftId;

  const navigate = useNavigate();
  const currencyCode = useCurrencyCode();
  const cardRef = useRef();
  const entry = useIntersectionObserver(cardRef, {
    freezeOnceVisible: true,
  });
  const { metadata: fakeMetadata, isLoading } = useNFTMetadata({
    id: nft.launcherId,
  });

  const isVisible = !!entry?.isIntersecting;

  const metadata = { ...fakeMetadata, ...nft };

  function handleClick() {
    navigate(`/dashboard/nfts/${nft.$nftId}`);
  }

  function handleSelectChange(event) {
    if (onSelect) {
      onSelect(event.target.checked);
    }
  }

  function handleClickRadio(event) {
    event.stopPropagation();

    if (selected && onSelect) {
      onSelect(false);
    }
  }

  return (
    <Card ref={cardRef}>
      {isLoading ? (
        <CardContent>
          <Loading center />
        </CardContent>
      ) : (
        <CardActionArea onClick={handleClick}>
          <CardContent>
            <Flex justifyContent="space-between" alignItems="top">
              <Flex flexDirection="column" gap={1}>
                <Typography variant="h6" noWrap>
                  {metadata.owner ?? ''}
                </Typography>
                <Typography color="textSecondary" noWrap>
                  {metadata.marketplace ?? ''}
                </Typography>
              </Flex>
              <Box mr={-1}>
                <Radio
                  checked={!!selected}
                  onClick={handleClickRadio}
                  onChange={handleSelectChange}
                  value={nftId}
                  name={`nft-${nftId}`}
                />
              </Box>
            </Flex>
          </CardContent>
          {isVisible ? <NFTPreview nft={nft} /> : <Box height="300px" />}
          <CardContent>
            <Flex flexDirection="column" gap={2}>
              <Flex flexDirection="column" gap={1}>
                {metadata.editionCount > 1 && (
                  <Flex justifyContent="space-between" alignItems="center">
                    <Typography variant="h6" noWrap>
                      {metadata.name}
                    </Typography>
                    <Typography>1/{metadata.editionCount}</Typography>
                  </Flex>
                )}
                {metadata.price && (
                  <Typography color="textSecondary">
                    <Trans>
                      Sold for {mojoToChiaLocaleString(metadata.price)}{' '}
                      {currencyCode}
                    </Trans>
                  </Typography>
                )}
              </Flex>
            </Flex>
          </CardContent>
          <StyledCardFooter>
            <Flex justifyContent="space-between" alignItems="center">
              <Tooltip title={nftId}>
                <Typography noWrap>
                  <Truncate>{nftId}</Truncate>
                </Typography>
              </Tooltip>
              <CopyToClipboard value={nftId} />
            </Flex>
          </StyledCardFooter>
        </CardActionArea>
      )}
    </Card>
  );
}
