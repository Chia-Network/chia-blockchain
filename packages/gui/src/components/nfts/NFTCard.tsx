import React from 'react';
import { useNFTMetadata } from '@chia/api-react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router-dom';
import { Box, Card, CardActionArea, CardMedia, CardContent, Typography, Radio } from '@mui/material';
import { CopyToClipboard, Flex, Loading, mojoToChiaLocaleString, useCurrencyCode } from '@chia/core';
import type NFT from '../../types/NFT';

export type NFTCardProps = {
  nft: NFT;
  onSelect?: (selected: boolean) => void;
  selected?: boolean;
};

export default function NFTCard(props: NFTCardProps) {
  const {
    nft: {
      id,
    },
    onSelect,
    selected,
  } = props;

  const navigate = useNavigate();
  const currencyCode = useCurrencyCode();
  const { metadata, isLoading } = useNFTMetadata({ id });
  const shortId = `${id.substr(0, 6)}...${id.substr(id.length - 6)}`;

  function handleClick() {
    navigate(`/dashboard/nfts/${id}`);
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
    <Card>
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
                  {metadata.owner}
                </Typography>
                <Typography color="textSecondary" noWrap>
                  {metadata.marketplace}
                </Typography>
              </Flex>
              <Box mr={-1}>
                <Radio
                  checked={!!selected}
                  onClick={handleClickRadio}
                  onChange={handleSelectChange}
                  value={id}
                  name={`nft-${id}`}
                />
              </Box>
            </Flex>
          </CardContent>

          <CardMedia src={metadata.image} component="img" height="300px" />

          <CardContent>
            <Flex flexDirection="column" gap={2}>
              <Flex flexDirection="column" gap={1}>
                <Flex justifyContent="space-between" alignItems="center">
                  <Typography variant="h6" noWrap>{metadata.name}</Typography>
                  <Typography>1/{metadata.total}</Typography>
                </Flex>

                <Typography color="textSecondary">
                  <Trans>Sold for {mojoToChiaLocaleString(metadata.price)} {currencyCode}</Trans>
                </Typography>
              </Flex>

              <Flex justifyContent="space-between" alignItems="center">
                <Typography noWrap>
                  <Trans>nft:chia:{shortId}</Trans>
                </Typography>
                <CopyToClipboard value={id} />
              </Flex>
            </Flex>
          </CardContent>
        </CardActionArea>
      )}
    </Card>
  );
}
