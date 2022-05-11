import React, { useEffect, useState } from 'react';
import { Trans } from '@lingui/macro';
import {
  Box,
  CardMedia,
} from '@mui/material';
import { Error, NotInterested, ImageNotSupported } from '@mui/icons-material';
import {
  IconMessage,
  Loading,
} from '@chia/core';
import styled from 'styled-components';
import useNFTHash from '../../hooks/useNFTHash';
import { type NFTInfo } from '@chia/api';

const StyledCardPreview = styled(Box)`
  height: ${({ height }) => height};
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  overflow: hidden;
`;

export type NFTPreviewProps = {
  nft: NFTInfo;
  height?: number | string;
};

export default function NFTPreview(props: NFTPreviewProps) {
  const {
    nft,
    nft: {
      dataUris,
    },
    height = '300px',
  } = props;

  /*
  const notAvailableNFT = {
    ...nft,
    dataUris: ['https://github.com/link-u/avif-sample-images/blob/master/fox.profile0.10bpc.yuv420.avif?raw=true'],
  };
  */

  const { isValid, isLoading, error } = useNFTHash(nft);
  const [mediaError, setMediaError] = useState();
  const hasFile = dataUris?.length > 0;

  useEffect(() => {
    setMediaError(undefined);
  }, [nft]);


  function handleMediaError(newMediaError) {
    setMediaError(newMediaError);
  }

  return (
    <StyledCardPreview height={height}>
      {!hasFile ? (
        <IconMessage icon={<NotInterested fontSize="large" />}>
          <Trans>No file available</Trans>
        </IconMessage>
      ) : isLoading ? (
        <Loading center>
          <Trans>Loading preview...</Trans>
        </Loading>
      ) : error ? (
        <IconMessage icon={<Error fontSize="large" />}>
          {error.message}
        </IconMessage>
      ) :!isValid ? (
        <IconMessage icon={<Error fontSize="large" />}>
          <Trans>File hash mismatch</Trans>
        </IconMessage>
      ) : mediaError ? (
        <IconMessage icon={<ImageNotSupported fontSize="large" />}>
          <Trans>No preview available</Trans>
        </IconMessage>
      ) : (
        <CardMedia
          src={dataUris?.[0]}
          component="img"
          height={height}
          onError={handleMediaError}
        />
      )}
    </StyledCardPreview>
  );
}
