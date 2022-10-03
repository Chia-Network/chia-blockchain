import { useEffect, useState, useCallback } from 'react';
import type NFTInfo from '@chia/api';
import getRemoteFileContent from '../util/getRemoteFileContent';
import { useLocalStorage } from '@chia/core';

export const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB

export default function useNFTMetadata(nft: NFTInfo) {
  const uri = nft?.metadataUris?.[0]; // ?? 'https://gist.githubusercontent.com/seeden/f648fc750c244f08ecb32507f217677a/raw/59fdfeb7a1c8d6d6afea5d86ecfdfd7f2d0167a5/metadata.json';
  const nftId = nft?.$nftId;

  const [isLoading, setIsLoadingContent] = useState<boolean>(true);
  const [errorContent, setErrorContent] = useState<Error | undefined>();
  const [metadata, setMetadata] = useState<any>();

  const [metadataCache, setMetadataCache] = useLocalStorage(
    `metadata-cache-${nftId}`,
    {},
  );

  async function getMetadataContents({ dataHash }): Promise<{
    data: string;
    encoding: string;
    isValid: boolean;
  }> {
    if (metadataCache.isValid !== undefined) {
      return {
        data: metadataCache.json,
        encoding: 'utf-8',
        isValid: metadataCache.isValid,
      };
    }

    return await getRemoteFileContent({
      nftId,
      uri,
      maxSize: MAX_FILE_SIZE,
      dataHash,
    });
  }

  const getMetadata = useCallback(async (uri) => {
    try {
      setIsLoadingContent(true);
      setErrorContent(undefined);
      setMetadata(undefined);

      if (!uri) {
        throw new Error('Invalid URI');
      }

      const {
        data: content,
        encoding,
        isValid,
      } = await getMetadataContents({ dataHash: nft.metadataHash });

      if (!isValid) {
        setMetadataCache({
          isValid: false,
        });
        throw new Error('Metadata hash mismatch');
      }

      let metadata = undefined;
      if (['utf8', 'utf-8'].includes(encoding.toLowerCase())) {
        metadata = JSON.parse(content);
      } else {
        // Special case where we don't know the encoding type -- assume UTF-8
        metadata = JSON.parse(
          Buffer.from(content, encoding as BufferEncoding).toString('utf8'),
        );
      }
      setMetadataCache({
        isValid: true,
        json: content,
      });
      setMetadata(metadata);
    } catch (error: any) {
      setErrorContent(error);
    } finally {
      setIsLoadingContent(false);
    }
  }, []);

  useEffect(() => {
    getMetadata(uri);
  }, [uri]);

  const error = errorContent;

  return {
    metadata,
    isLoading,
    error,
  };
}
