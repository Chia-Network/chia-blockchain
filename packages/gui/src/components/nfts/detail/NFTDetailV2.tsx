import React, { useMemo, useState, useEffect } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import {
  Back,
  Flex,
  LayoutDashboardSub,
  Loading,
  useOpenDialog,
} from '@chia/core';
import type { NFTInfo } from '@chia/api';
import { useGetNFTWallets } from '@chia/api-react';
import { Box, Grid, Typography, IconButton, Button } from '@mui/material';
import { MoreVert } from '@mui/icons-material';
import { useParams } from 'react-router-dom';
import NFTPreview from '../NFTPreview';
import NFTProperties from '../NFTProperties';
import NFTRankings from '../NFTRankings';
import NFTDetails from '../NFTDetails';
import useFetchNFTs from '../../../hooks/useFetchNFTs';
import useNFTMetadata from '../../../hooks/useNFTMetadata';
import NFTContextualActions, {
  NFTContextualActionTypes,
} from '../NFTContextualActions';
import NFTPreviewDialog from '../NFTPreviewDialog';
import NFTProgressBar from '../NFTProgressBar';
import { useLocalStorage } from '@chia/core';
import { isImage } from '../../../util/utils.js';

export default function NFTDetail() {
  const { nftId } = useParams();
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
  const openDialog = useOpenDialog();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );

  const [validationProcessed, setValidationProcessed] = useState(false);
  const nftRef = React.useRef(null);
  const [isValid, setIsValid] = useState(false);

  const nft: NFTInfo | undefined = useMemo(() => {
    if (!nfts) {
      return;
    }
    return nfts.find((nft: NFTInfo) => nft.$nftId === nftId);
  }, [nfts]);

  const uri = nft?.dataUris?.[0];

  const [contentCache] = useLocalStorage(`content-cache-${nft.$nftId}`, {});

  const [validateNFT, setValidateNFT] = useState(false);

  nftRef.current = nft;

  const { metadata, isLoading: isLoadingMetadata, error } = useNFTMetadata(nft);

  const ValidateContainer = styled.div`
    padding-top: 25px;
    text-align: center;
  `;

  const ErrorMessage = styled.div`
    color: red;
  `;

  const isLoading = isLoadingWallets || isLoadingNFTs || isLoadingMetadata;

  if (isLoading) {
    return <Loading center />;
  }

  function handleShowFullScreen() {
    if (isImage(uri)) {
      openDialog(<NFTPreviewDialog nft={nft} />);
    }
  }

  function renderValidationState() {
    if (validateNFT && !validationProcessed) {
      return <Trans>Validating hash...</Trans>;
    } else if (contentCache.valid || (validationProcessed && isValid)) {
      return <Trans>Hash is validated.</Trans>;
    } else if (contentCache.valid === false) {
      return (
        <ErrorMessage>
          <Trans>Hash mismatch.</Trans>
        </ErrorMessage>
      );
    } else {
      return (
        <Button
          onClick={() => setValidateNFT(true)}
          variant="outlined"
          size="large"
        >
          <Trans>Validate SHA256 SUM</Trans>
        </Button>
      );
    }
  }

  return (
    <Flex flexDirection="column" gap={2}>
      <Flex
        sx={{ bgcolor: 'background.paper' }}
        justifyContent="center"
        py={{ xs: 2, sm: 3, md: 7 }}
        px={3}
      >
        <Flex
          position="relative"
          maxWidth="1200px"
          width="100%"
          justifyContent="center"
        >
          <Box
            overflow="hidden"
            alignItems="center"
            justifyContent="center"
            maxWidth="800px"
            alignSelf="center"
            width="100%"
            position="relative"
          >
            {nft && (
              <Flex flexDirection="column">
                <Box onClick={handleShowFullScreen} sx={{ cursor: 'pointer' }}>
                  <NFTPreview
                    nft={nft}
                    width="100%"
                    height="412px"
                    fit="contain"
                    validateNFT={validateNFT}
                  />
                </Box>
                <ValidateContainer>{renderValidationState()}</ValidateContainer>
                <NFTProgressBar
                  uri={uri}
                  setValidationProcessed={setValidationProcessed}
                  setIsValid={setIsValid}
                  setValidateNFT={setValidateNFT}
                />
              </Flex>
            )}
          </Box>
          <Box position="absolute" left={1} top={1}>
            <Back iconStyle={{ backgroundColor: 'action.hover' }} />
          </Box>
        </Flex>
      </Flex>
      <LayoutDashboardSub>
        <Flex
          flexDirection="column"
          gap={2}
          maxWidth="1200px"
          width="100%"
          alignSelf="center"
          mb={3}
        >
          <Flex alignItems="center" justifyContent="space-between">
            <Typography variant="h4" overflow="hidden">
              {metadata?.name ?? <Trans>Title Not Available</Trans>}
            </Typography>
            <NFTContextualActions
              selection={{ items: [nft] }}
              availableActions={NFTContextualActionTypes.All}
              toggle={
                <IconButton>
                  <MoreVert />
                </IconButton>
              }
            />
          </Flex>

          <Grid spacing={{ xs: 6, lg: 8 }} container>
            <Grid item xs={12} md={6}>
              <Flex flexDirection="column" gap={3}>
                <Flex flexDirection="column" gap={1}>
                  <Typography variant="h6">
                    <Trans>Description</Trans>
                  </Typography>

                  <Typography sx={{ whiteSpace: 'pre-line' }} overflow="hidden">
                    {metadata?.description ?? <Trans>Not Available</Trans>}
                  </Typography>
                </Flex>
                {metadata?.collection?.name && (
                  <Flex flexDirection="column" gap={1}>
                    <Typography variant="h6">
                      <Trans>Collection</Trans>
                    </Typography>

                    <Typography overflow="hidden">
                      {metadata?.collection?.name ?? (
                        <Trans>Not Available</Trans>
                      )}
                    </Typography>
                  </Flex>
                )}
                {(nft?.editionTotal ?? 0) > 1 && (
                  <Flex flexDirection="column" gap={1}>
                    <Typography variant="h6">
                      <Trans>Edition Number</Trans>
                    </Typography>

                    <Typography>
                      <Trans>
                        {nft.editionNumber} of {nft.editionTotal}
                      </Trans>
                    </Typography>
                  </Flex>
                )}
                <NFTProperties attributes={metadata?.attributes} />
                <NFTRankings attributes={metadata?.attributes} />
              </Flex>
            </Grid>
            <Grid item xs={12} md={6}>
              <NFTDetails nft={nft} metadata={metadata} />
            </Grid>
          </Grid>

          {/**
          <Flex flexDirection="column" gap={1}>
            <Typography variant="h6">
              <Trans>Item Activity</Trans>
            </Typography>
            <Table cols={cols} rows={metadata.activity} />
          </Flex>
          */}
        </Flex>
      </LayoutDashboardSub>
    </Flex>
  );
}
