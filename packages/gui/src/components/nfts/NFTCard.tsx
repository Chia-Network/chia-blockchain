import React from 'react';
import { useNFTMetadata } from '@chia/api-react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Card,
  CardActionArea,
  CardMedia,
  CardContent,
  Typography,
  Radio,
} from '@mui/material';
import {
  CopyToClipboard,
  Flex,
  Loading,
  mojoToChiaLocaleString,
  useCurrencyCode,
} from '@chia/core';
import type NFTInfo from '@chia/api';

export type NFTCardProps = {
  nft: NFTInfo;
  onSelect?: (selected: boolean) => void;
  selected?: boolean;
};

export default function NFTCard(props: NFTCardProps) {
  const { nft, onSelect, selected } = props;

  const navigate = useNavigate();
  const currencyCode = useCurrencyCode();
  const { metadata: fakeMetadata, isLoading } = useNFTMetadata({
    id: nft.launcherId,
  });
  const id = nft.id;
  const metadata = { ...fakeMetadata, ...nft };
  const shortId = `${id.substr(0, 6)}...${id.substr(id.length - 6)}`;

  function handleClick() {
    navigate(`/dashboard/nfts/${nft.launcherId}`);
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
                  value={id}
                  name={`nft-${id}`}
                />
              </Box>
            </Flex>
          </CardContent>

          <CardMedia
            src={metadata.dataUris?.[0]}
            component="img"
            height="300px"
          />

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

              <Flex justifyContent="space-between" alignItems="center">
                <Typography noWrap>
                  <Trans>{shortId}</Trans>
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
