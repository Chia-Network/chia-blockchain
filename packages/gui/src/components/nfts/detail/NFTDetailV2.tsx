import React, { useMemo, useEffect, useRef } from 'react';
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
import {
  Box,
  Grid,
  Typography,
  IconButton,
  Dialog,
  Paper,
  Button,
} from '@mui/material';
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
import NFTProgressBar from '../NFTProgressBar';

const ipcRenderer = (window as any).ipcRenderer;

export default function NFTDetail() {
  const { nftId } = useParams();
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );

  const [progressBarWidth, setProgressBarWidth] = React.useState(-1);
  const [validated, setValidated] = React.useState(0);
  const nftRef = React.useRef(null);

  useEffect(() => {
    validateSha256Remote(false); // false parameter means only validate files smaller than MAX_FILE_SIZE
    ipcRenderer.on('sha256DownloadProgress', progressListener);
    ipcRenderer.on('sha256hash', gotHash);
    return () => {
      ipcRenderer.off('sha256DownloadProgress', progressListener);
      ipcRenderer.off('sha256hash', gotHash);
    };
  }, []);

  const nft: NFTInfo | undefined = useMemo(() => {
    if (!nfts) {
      return;
    }
    return nfts.find((nft: NFTInfo) => nft.$nftId === nftId);
  }, [nfts]);

  nftRef.current = nft;

  function progressListener(_event, progressObject: any) {
    const nft = nftRef.current;
    if (
      nft &&
      nft.dataUris &&
      Array.isArray(nft.dataUris) &&
      nft.dataUris[0] === progressObject.uri
    ) {
      setProgressBarWidth(progressObject.progress);
      if (progressObject.progress === 1) {
        setProgressBarWidth(-1);
      }
    }
  }

  function gotHash(_event, hash) {
    if (nftRef.current) {
      if (`0x${hash}` === nftRef.current.dataHash) {
        setValidated(1);
      } else {
        setValidated(-1);
      }
    }
  }

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

  function validateSha256Remote(force: boolean) {
    const ipcRenderer = (window as any).ipcRenderer;
    if (nft && Array.isArray(nft.dataUris) && nft.dataUris[0]) {
      ipcRenderer.invoke('validateSha256Remote', {
        uri: nft.dataUris[0],
        force,
      });
    }
  }

  function renderValidationState() {
    if (progressBarWidth > 0 && progressBarWidth < 1) {
      return <Trans>Validating hash...</Trans>;
    } else if (validated === 1) {
      return <Trans>Hash is validated.</Trans>;
    } else if (validated === -1) {
      return (
        <ErrorMessage>
          <Trans>Hash mismatch.</Trans>
        </ErrorMessage>
      );
    } else {
      return (
        <Button
          onClick={() => validateSha256Remote(true)}
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
              <Box sx={{ cursor: 'pointer' }}>
                <NFTPreview
                  nft={nft}
                  width="100%"
                  height="412px"
                  fit="contain"
                />
                <ValidateContainer>{renderValidationState()}</ValidateContainer>
                <NFTProgressBar percentage={progressBarWidth} />
              </Box>
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

                  <Typography overflow="hidden">
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
                {(nft?.seriesTotal ?? 0) > 1 && (
                  <Flex flexDirection="column" gap={1}>
                    <Typography variant="h6">
                      <Trans>Series Number</Trans>
                    </Typography>

                    <Typography>
                      <Trans>
                        {nft.seriesNumber} of {nft.seriesTotal}
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
