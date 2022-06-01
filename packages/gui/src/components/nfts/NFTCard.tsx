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
  const { nft, canExpandDetails, availableActions } = props;
  const nftId = nft.$nftId;

  const navigate = useNavigate();

  const { metadata, isLoading } = useNFTMetadata(nft);

  function handleClick() {
    navigate(`/dashboard/nfts/${nft.$nftId}`);
  }

  const transferPending = nft.pendingTransaction === 1;
  const unavailableActions = transferPending
    ? NFTContextualActionTypes.CreateOffer | NFTContextualActionTypes.Transfer
    : NFTContextualActionTypes.None;
  const actions = availableActions & ~unavailableActions;

  const overlay = transferPending ? (
    <>
      <Box
        sx={{
          boxSizing: 'border-box',
          position: 'absolute',
          top: '0',
          left: '0',
          backgroundColor: 'rgba(255, 255, 255, 0.5)',
          boxShadow: '0px 4px 4px rgba(0, 0, 0, 0.5)',
          backdropFilter: 'blur(16px)',
          height: '40px',
          width: '100%',
          zIndex: 'modal',
        }}
      ></Box>
      <Box
        sx={{
          position: 'absolute',
          top: '0',
          right: '0',
          height: '40px',
          width: '100%',
          zIndex: 'tooltip',
        }}
      >
        <Flex
          style={{ height: '100%' }}
          alignItems="center"
          justifyContent="center"
        >
          <Typography variant="caption" color="rgba(0,0,0,1)">
            <Trans>Pending Transfer</Trans>
          </Typography>
        </Flex>
      </Box>
    </>
  ) : null;

  return (
    <Card>
      {isLoading ? (
        <CardContent>
          <Loading center />
        </CardContent>
      ) : (
        <>
          <CardActionArea onClick={handleClick} disabled={!canExpandDetails}>
            {overlay}
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
                  availableActions={actions}
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
