import React from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router-dom';
import { Card, CardActionArea, CardContent, Typography } from '@mui/material';
import { IconButton, Flex, Loading } from '@chia/core';
import { MoreVert } from '@mui/icons-material';
import styled from 'styled-components';
import NFTPreview from './NFTPreview';
import { type NFTInfo } from '@chia/api';
import NFTContextualActions, {
  NFTContextualActionTypes,
} from './NFTContextualActions';
import useNFTMetadata from '../../hooks/useNFTMetadata';

const StyledCardContent = styled(CardContent)`
  //padding-top: ${({ theme }) => theme.spacing(1)};
  // padding-bottom: ${({ theme }) => theme.spacing(1)} !important;
`;

const StyledLoadingCardContent = styled(CardContent)`
  min-height: 362px;
  display: flex;
  align-items: center;
  justify-content: center;
`;

export type NFTCardProps = {
  nft: NFTInfo;
  onSelect?: (selected: boolean) => void;
  selected?: boolean;
  canExpandDetails: boolean;
  availableActions: NFTContextualActionTypes;
  isOffer: boolean;
};

export default function NFTCard(props: NFTCardProps) {
  const {
    nft,
    canExpandDetails = true,
    availableActions = NFTContextualActionTypes.None,
    isOffer,
  } = props;

  const navigate = useNavigate();

  const { metadata, isLoading, error } = useNFTMetadata(nft);

  function handleClick() {
    if (canExpandDetails) {
      navigate(`/dashboard/nfts/${nft.$nftId}`);
    }
  }

  return (
    <Flex flexDirection="column" flexGrow={1}>
      <Card sx={{ borderRadius: '8px' }} variant="outlined">
        {isLoading ? (
          <StyledLoadingCardContent>
            <Loading center />
          </StyledLoadingCardContent>
        ) : (
          <>
            <CardActionArea onClick={handleClick}>
              <NFTPreview
                nft={nft}
                fit="cover"
                isPreview
                metadata={metadata}
                isLoadingMetadata={isLoading}
                disableThumbnail={isOffer}
                metadataError={error}
              />
            </CardActionArea>
            <CardActionArea
              onClick={() => canExpandDetails && handleClick()}
              component="div"
            >
              <StyledCardContent>
                <Flex justifyContent="space-between" alignItems="center">
                  <Flex gap={1} alignItems="center" minWidth={0}>
                    <Typography noWrap>
                      {metadata?.name ?? <Trans>Title Not Available</Trans>}
                    </Typography>
                  </Flex>
                  {availableActions !== NFTContextualActionTypes.None && (
                    <NFTContextualActions
                      selection={{ items: [nft] }}
                      availableActions={availableActions}
                      toggle={
                        <IconButton>
                          <MoreVert />
                        </IconButton>
                      }
                    />
                  )}
                </Flex>
              </StyledCardContent>
            </CardActionArea>
          </>
        )}
      </Card>
    </Flex>
  );
}
