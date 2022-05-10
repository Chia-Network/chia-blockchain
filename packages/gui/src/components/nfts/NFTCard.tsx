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
import { Verified, Report } from '@mui/icons-material';
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
import useNFTHash from '../../hooks/useNFTHash';
import { type NFTInfo } from '@chia/api';

const StyledCardPreview = styled(Box)`
  height: 300px;
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  overflow: hidden;
`;

export type NFTCardProps = {
  nft: NFTInfo;
  onSelect?: (selected: boolean) => void;
  selected?: boolean;
};

export default function NFTCard(props: NFTCardProps) {
  const {
    nft,
    onSelect,
    selected,
    nft: {
      id,
      dataUris,
    }
  } = props;

  const navigate = useNavigate();
  const currencyCode = useCurrencyCode();
  const { metadata: fakeMetadata, isLoading } = useNFTMetadata({
    id: nft.launcherId,
  });

  const { isValid, isLoading: isLoadingPreview } = useNFTHash(nft);

  const metadata = { ...fakeMetadata, ...nft };
  const hasFile = dataUris?.length > 0;

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

          {hasFile && (
            <StyledCardPreview>
              {isLoadingPreview ? (
                <Loading center>
                  <Trans>Loading preview...</Trans>
                </Loading>
              ) : (
                <>
                  <CardMedia
                    src={dataUris?.[0]}
                    component="img"
                    height="300px"
                  />
                  <Tooltip title={isValid ? <Trans>File hash verified</Trans> : <Trans>File hash mismatch</Trans>}>
                    <Box
                      display="flex"
                      position="absolute"
                      top={'0.75rem'}
                      right={'1rem'}
                      backgroundColor="rgba(0,0,0,0.35)"
                      borderRadius="50%"
                      width={30}
                      height={30}
                      overflow="hidden"
                      justifyContent="center"
                      alignItems="center"
                    >
                      {isValid
                        ? <Verified fontSize="small" />
                        : <Report color="warning" fontSize="small" />}
                    </Box>
                  </Tooltip>
                </>
              )}
            </StyledCardPreview>
          )}

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
                <Tooltip title={id}>
                  <Typography noWrap>
                    <Truncate>{id}</Truncate>
                  </Typography>
                </Tooltip>
                <CopyToClipboard value={id} />
              </Flex>
            </Flex>
          </CardContent>
        </CardActionArea>
      )}
    </Card>
  );
}
