import React, { useEffect, useMemo, useState } from 'react';
import { renderToString } from 'react-dom/server';
import { Trans } from '@lingui/macro';
import { Box } from '@mui/material';
import { Error, NotInterested } from '@mui/icons-material';
import { IconMessage, Loading, Flex, SandboxedIframe } from '@chia/core';
import styled from 'styled-components';
import useNFTHash from '../../hooks/useNFTHash';
import { type NFTInfo } from '@chia/api';
import isURL from 'validator/lib/isURL';
import NFTStatusBar from './NFTStatusBar';

const StyledCardPreview = styled(Box)`
  height: ${({ height }) => height};
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  overflow: hidden;
`;

const StyledIframe = styled('iframe')`
  position: relative;
  pointer-events: none;
  width: 100%;
  height: 100%;
  opacity: ${({ isVisible }) => (isVisible ? 1 : 0)};
`;

export type NFTPreviewProps = {
  nft: NFTInfo;
  height?: number | string;
  width?: number | string;
  fit?: 'cover' | 'contain' | 'fill';
};

export default function NFTPreview(props: NFTPreviewProps) {
  const {
    nft,
    nft: { dataUris },
    height = '300px',
    width = '100%',
    fit = 'cover',
  } = props;

  /*
  const notAvailableNFT = {
    ...nft,
    dataUris: ['https://github.com/link-u/avif-sample-images/blob/master/fox.profile0.10bpc.yuv420.avif?raw=true'],
  };
  */

  const [loaded, setLoaded] = useState(false);
  const { isValid, isLoading, error } = useNFTHash(nft);
  const hasFile = dataUris?.length > 0;
  const file = dataUris?.[0];

  useEffect(() => {
    setLoaded(false);
  }, [nft]);

  const isUrlValid = useMemo(() => {
    if (!file) {
      return false;
    }

    return isURL(file);
  }, [file]);

  const srcDoc = useMemo(() => {
    if (!file) {
      return;
    }

    const style = `
      html, body {
        border: 0px;
        margin: 0px;
        padding: 0px;
        height: 100%;
        width: 100%;
      }

      img {
        object-fit: ${fit};
      }
    `;

    return renderToString(
      <html>
        <head>
          <style dangerouslySetInnerHTML={{ __html: style }} />
        </head>
        <body>
          <img src={file} alt="Preview" width="100%" height="100%" />
        </body>
      </html>,
    );
  }, [file]);

  const [statusText, isStatusError] = useMemo(() => {
    if (nft.pendingTransaction) {
      return [<Trans>Pending Transfer</Trans>, false];
    } else if (error?.message === 'Hash mismatch') {
      return [<Trans>Image Hash Mismatch</Trans>, true];
    }
    return [undefined, false];
  }, [nft, isValid, error]);

  function handleLoadedChange(loadedValue) {
    setLoaded(loadedValue);
  }

  return (
    <StyledCardPreview height={height} width={width}>
      <NFTStatusBar statusText={statusText} showDropShadow={true} />
      {!hasFile ? (
        <IconMessage icon={<NotInterested fontSize="large" />}>
          <Trans>No file available</Trans>
        </IconMessage>
      ) : !isUrlValid ? (
        <IconMessage icon={<Error fontSize="large" />}>
          <Trans>Preview URL is not valid</Trans>
        </IconMessage>
      ) : isLoading ? (
        <Loading center>
          <Trans>Loading preview...</Trans>
        </Loading>
      ) : error && !isStatusError ? (
        <IconMessage icon={<Error fontSize="large" />}>
          {error.message}
        </IconMessage>
      ) : (
        <>
          {!loaded && (
            <Flex
              position="absolute"
              left="0"
              top="0"
              bottom="0"
              right="0"
              justifyContent="center"
              alignItems="center"
            >
              <Loading center>
                <Trans>Loading preview...</Trans>
              </Loading>
            </Flex>
          )}
          <SandboxedIframe
            srcDoc={srcDoc}
            height={height}
            onLoadedChange={handleLoadedChange}
            hideUntilLoaded
          />
        </>
      )}
    </StyledCardPreview>
  );
}
