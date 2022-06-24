import React from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Card,
  CardActionArea,
  CardContent,
  Typography,
} from '@mui/material';
import {
  IconButton,
  CopyToClipboard,
  Flex,
  Loading,
  Tooltip,
  Truncate,
} from '@chia/core';
import { MoreVert } from '@mui/icons-material';
import styled from 'styled-components';
import NFTPreview from './NFTPreview';
import { type NFTInfo } from '@chia/api';
import useNFTMetadata from '../../hooks/useNFTMetadata';
import NFTContextualActions, {
  NFTContextualActionTypes,
} from './NFTContextualActions';

const StyledCardFooter = styled(CardContent)`
  padding-top: ${({ theme }) => theme.spacing(1)};
  padding-bottom: ${({ theme }) => theme.spacing(1)} !important;
  background-color: ${({ theme }) => theme.palette.action.hover};
`;

const StyledCardContent = styled(CardContent)`
  //padding-top: ${({ theme }) => theme.spacing(1)};
  // padding-bottom: ${({ theme }) => theme.spacing(1)} !important;
`;

export type NFTCardProps = {
  nft: NFTInfo;
  onSelect?: (selected: boolean) => void;
  selected?: boolean;
  canExpandDetails: boolean;
  availableActions: NFTContextualActionTypes;
};

export default function NFTCard(props: NFTCardProps) {
  const { nft, canExpandDetails = true, availableActions = NFTContextualActionTypes.None } = props;
  const nftId = nft.$nftId;

  const navigate = useNavigate();

  const { metadata, isLoading } = useNFTMetadata(nft);

  function handleClick() {
    navigate(`/dashboard/nfts/${nft.$nftId}`);
  }

  return (
    <Flex flexDirection="column" flexGrow={1}>
      <Card sx={{ borderRadius: '8px' }}>
        {isLoading ? (
          <CardContent>
            <Loading center />
          </CardContent>
        ) : (
          <>
            <CardActionArea onClick={handleClick} disabled={!canExpandDetails}>
              <NFTPreview nft={nft} fit="cover" />
            </CardActionArea>
            <CardActionArea onClick={() => canExpandDetails && handleClick()}>
              <StyledCardContent>
                <Flex justifyContent="space-between" alignItems="center">
                  <Flex gap={1} alignItems="center">
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
