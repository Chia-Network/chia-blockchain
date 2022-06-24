import React, { useEffect, useMemo, useState, type ReactNode, Fragment } from 'react';
import { renderToString } from 'react-dom/server';
import { t, Trans } from '@lingui/macro';
import { Box, Button } from '@mui/material';
import { NotInterested, Error as ErrorIcon } from '@mui/icons-material';
import { IconMessage, Loading, Flex, SandboxedIframe, usePersistState } from '@chia/core';
import styled from 'styled-components';
import { type NFTInfo } from '@chia/api';
import isURL from 'validator/lib/isURL';
import useNFTHash from '../../hooks/useNFTHash';
import NFTStatusBar from './NFTStatusBar';

function prepareErrorMessage(error: Error): ReactNode {
  if (error.message === 'Response too large') {
    return (
      <Trans>File is over 10MB</Trans>
    );
  }

  return error.message;
}

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
  width?: number | string;
  fit?: 'cover' | 'contain' | 'fill';
  elevate?: boolean;
  background?: any;
};

export default function NFTPreview(props: NFTPreviewProps) {
  const {
    nft,
    nft: { dataUris },
    height = '300px',
    width = '100%',
    fit = 'cover',
    background: Background = Fragment,
  } = props;

  const [loaded, setLoaded] = useState(false);
  const { isValid, isLoading, error } = useNFTHash(nft);
  const hasFile = dataUris?.length > 0;
  const file = dataUris?.[0];
  const [ignoreError, setIgnoreError] = usePersistState<boolean>(false, `nft-preview-ignore-error-${nft.$nftId}-${file}`);

  useEffect(() => {
    setLoaded(false);
  }, [file]);

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
          <img src={file} alt={t`Preview`} width="100%" height="100%" />
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

  function handleIgnoreError(event) {
    event.stopPropagation();

    setIgnoreError(true);
  }

  return (
    <StyledCardPreview height={height} width={width}>
      <NFTStatusBar statusText={statusText} showDropShadow={true} />
      {!hasFile ? (
        <Background>
          <IconMessage icon={<NotInterested fontSize="large" />}>
            <Trans>No file available</Trans>
          </IconMessage>
        </Background>
      ) : !isUrlValid ? (
        <Background>
          <IconMessage icon={<ErrorIcon fontSize="large" />}>
            <Trans>Preview URL is not valid</Trans>
          </IconMessage>
        </Background>
      ) : isLoading ? (
        <Background>
          <Loading center>
            <Trans>Loading preview...</Trans>
          </Loading>
        </Background>
      ) : error && !isStatusError && !ignoreError ? (
        <Background>
          <Flex direction="column" gap={2}>
            <IconMessage icon={<ErrorIcon fontSize="large" />}>
              {prepareErrorMessage(error)}
            </IconMessage>
            <Button onClick={handleIgnoreError} variant="outlined" size="small" color="secondary">
              <Trans>Show Preview</Trans>
            </Button>
          </Flex>
        </Background>
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
