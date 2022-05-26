import React from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router-dom';
import { Card, CardActionArea, CardContent, Typography } from '@mui/material';
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
  const { nft, canExpandDetails, availableActions } = props;
  const nftId = nft.$nftId;

  const navigate = useNavigate();

  const { metadata, isLoading } = useNFTMetadata(nft);

  function handleClick() {
    navigate(`/dashboard/nfts/${nft.$nftId}`);
  }

  return (
    <Card>
      {isLoading ? (
        <CardContent>
          <Loading center />
        </CardContent>
      ) : (
        <>
          <CardActionArea onClick={handleClick} disabled={!canExpandDetails}>
            <NFTPreview nft={nft} />
            <StyledCardContent>
              <Typography noWrap>
                {metadata?.name ?? <Trans>Title Not Available</Trans>}
              </Typography>
            </StyledCardContent>
          </CardActionArea>
          <StyledCardFooter>
            <Flex justifyContent="space-between" alignItems="center">
              <Flex gap={1} alignItems="center">
                <CopyToClipboard
                  value={nftId}
                  color="#90A4AE"
                  size="small"
                  sx={{ color: '#90A4AE' }}
                />
                <Tooltip title={nftId}>
                  <Typography color="textSecondary" variant="body2" noWrap>
                    <Truncate>{nftId}</Truncate>
                  </Typography>
                </Tooltip>
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
          </StyledCardFooter>
        </>
      )}
    </Card>
  );
}

NFTCard.defaultProps = {
  canExpandDetails: true,
  availableActions: NFTContextualActionTypes.None,
};
