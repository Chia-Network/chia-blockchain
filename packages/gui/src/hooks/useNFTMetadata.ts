import { useEffect, useState, useCallback } from 'react';
import type NFTInfo from '@chia/api';
import useVerifyURIHash from './useVerifyURIHash';
import getRemoteFileContent from '../util/getRemoteFileContent';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

export default function useNFTMetadata(nft: NFTInfo) {
  const metadataHash = nft?.metadataHash; // || '371F6B9B4BD20A59E65CCF528A10F2E64EBDD848727981A12D5BAD32380697A7';
  const uri = nft?.metadataUris?.[0]; // ?? 'https://gist.githubusercontent.com/seeden/f648fc750c244f08ecb32507f217677a/raw/59fdfeb7a1c8d6d6afea5d86ecfdfd7f2d0167a5/metadata.json';

  const [isLoadingContent, setIsLoadingContent] = useState<boolean>(false);
  const [errorContent, setErrorContent] = useState<Error | undefined>();
  const [metadata, setMetadata] = useState<any>();

  const {
    isValid,
    isLoading: isLoadingHash,
    error: errorHash,
  } = useVerifyURIHash(uri, metadataHash);

  const getMetadata = useCallback(async (uri) => {
    try {
      setIsLoadingContent(true);
      setErrorContent(undefined);
      setMetadata(undefined);

      if (!uri) {
        throw new Error('Invalid URI');
      }

      const { data: content, encoding } = await getRemoteFileContent(
        uri,
        MAX_FILE_SIZE,
      );

      let metadata = undefined;
      if (['utf8', 'utf-8'].includes(encoding.toLowerCase())) {
        metadata = JSON.parse(content);
      } else {
        // Special case where we don't know the encoding type -- assume UTF-8
        metadata = JSON.parse(
          Buffer.from(content, encoding as BufferEncoding).toString('utf8'),
        );
      }

      setMetadata(metadata);
    } catch (error: any) {
      setErrorContent(error);
    } finally {
      setIsLoadingContent(false);
    }
  }, []);

  useEffect(() => {
    if (isValid) {
      getMetadata(uri);
    }
  }, [uri, isValid]);

  const isLoading = isLoadingHash || isLoadingContent;
  const error = errorHash || errorContent;

  return {
    metadata,
    isValid,
    isLoading,
    error,
  };
}
