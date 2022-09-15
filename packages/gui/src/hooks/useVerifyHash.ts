import { useState, useEffect } from 'react';
import isURL from 'validator/lib/isURL';

import getRemoteFileContent from '../util/getRemoteFileContent';
import { MAX_FILE_SIZE } from './useNFTMetadata';
import { mimeTypeRegex, isImage } from '../util/utils.js';
import { type NFTInfo } from '@chia/api';
import { useLocalStorage } from '@chia/core';

import { FileType } from '../util/getRemoteFileContent';

function isAudio(uri: string) {
  return mimeTypeRegex(uri, /^audio/);
}

type VerifyHash = {
  nft: NFTInfo;
  ignoreSizeLimit: boolean;
  metadata?: any;
  metadataError?: any;
  isPreview: boolean;
  dataHash: string;
  nftId: string;
  validateNFT: boolean;
};

let encoding: string = 'binary';

export default function useVerifyHash(props: VerifyHash): {
  isValid: boolean;
  isLoading: boolean;
  error: string | undefined;
  thumbnail: any;
  isValidationProcessed: boolean;
  validateNFT: boolean;
  encoding: string;
} {
  const {
    nft,
    ignoreSizeLimit,
    metadata,
    metadataError,
    isPreview,
    dataHash,
    nftId,
    validateNFT,
  } = props;
  const [isValid, setIsValid] = useState(false);
  const [isValidationProcessed, setIsValidationProcessed] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [thumbnail, setThumbnail] = useState({});
  const [thumbCache, setThumbCache] = useLocalStorage(
    `thumb-cache-${nftId}`,
    {},
  );
  const [contentCache, setContentCache] = useLocalStorage(
    `content-cache-${nftId}`,
    {},
  );
  const [forceReloadNFT] = useLocalStorage(`force-reload-${nftId}`, false);

  const uri = nft.dataUris?.[0];

  let lastError: any;

  async function validateHash(metadata: any): Promise<void> {
    let uris: string[] = [];
    let videoThumbValid: boolean = false;
    let imageThumbValid: boolean = false;

    setError(undefined);

    setIsLoading(true);
    setIsValid(false);

    if (metadata.preview_video_uris && !metadata.preview_video_hash) {
      setIsLoading(false);
      setError('missing preview_video_hash');
    } else if (metadata.preview_image_uris && !metadata.preview_image_hash) {
      setIsLoading(false);
      setIsValid(false);
      setError('missing preview_image_hash');
    } else {
      if (metadata['preview_video_uris']) {
        /* if it's cached, don't try to validate hash at all */
        if (thumbCache.video) {
          setError(undefined);
          setThumbnail({
            video: `cached://${Buffer.from(
              thumbCache.video,
              'base64',
            ).toString()}`,
          });
          setIsLoading(false);
          videoThumbValid = true;
          return;
        } else {
          uris = metadata['preview_video_uris'];
          for (let i = 0; i < uris.length; i++) {
            const videoUri = uris[i];
            try {
              if (!isURL(videoUri)) {
                setError('Invalid URI');
              }
              const { data: content } = await getRemoteFileContent({
                uri: videoUri,
                forceCache: true,
                nftId,
                type: FileType.Video,
                dataHash: metadata['preview_video_hash'],
              });
              if (content !== 'valid') {
                lastError = 'thumbnail hash mismatch';
              }
              videoThumbValid = content === 'valid';
            } catch (e: any) {
              /* if we already found content that is hash mismatched, show mismatch error! */
              lastError = lastError || 'failed fetch content';
            }
            if (videoThumbValid) {
              const cachedUri = `${nftId}_${videoUri}`;
              setThumbnail({
                video: `cached://${cachedUri}`,
              });
              setThumbCache({
                video: Buffer.from(cachedUri).toString('base64'),
              });
              setError(undefined);
              setIsLoading(false);
              return;
            }
          }
          if (lastError) {
            setError(lastError);
          }
        }
      }

      if (metadata['preview_image_uris'] && !videoThumbValid) {
        uris = metadata['preview_image_uris'];
        for (let i = 0; i < uris.length; i++) {
          const imageUri = uris[i];
          /* if it's cached, don't try to validate hash at all */
          if (thumbCache.image) {
            setError(undefined);
            setThumbnail({
              image: `cached://${Buffer.from(
                thumbCache.image,
                'base64',
              ).toString()}`,
            });
            setIsLoading(false);
            return;
          }

          try {
            if (!isURL(imageUri)) {
              setError('Invalid URI');
            }
            const { data: content } = await getRemoteFileContent({
              uri: imageUri,
              forceCache: true,
              nftId,
              dataHash: metadata['preview_image_hash'],
              type: FileType.Image,
            });
            imageThumbValid = content === 'valid';
          } catch (e: any) {
            /* if we already found content that is hash mismatched, show mismatch error! */
            lastError = lastError || 'failed fetch content';
          }
          if (imageThumbValid) {
            const cachedImageUri = `${nftId}_${imageUri}`;
            setThumbCache({
              image: Buffer.from(cachedImageUri).toString('base64'),
            });
            setError(undefined);
            setThumbnail({ image: `cached://${cachedImageUri}` });
            setIsLoading(false);
            return;
          }
        }
      }
      if (isImage(uri) || !isPreview) {
        if (contentCache.binary) {
          setThumbnail({
            binary: `cached://${Buffer.from(
              contentCache.binary,
              'base64',
            ).toString()}`,
          });
          if (contentCache.valid === false) {
            lastError = 'Hash mismatch';
          }
        } else {
          try {
            const { data: content, encoding: fileEncoding } =
              await getRemoteFileContent({
                uri,
                maxSize:
                  ignoreSizeLimit || validateNFT ? Infinity : MAX_FILE_SIZE,
                forceCache: true,
                nftId,
                type: FileType.Binary,
                dataHash,
              });

            encoding = fileEncoding;

            if (content !== 'valid') {
              lastError = 'Hash mismatch';
            }
          } catch (e: any) {
            lastError = e.message;
            setError(e.message);
          }
          if (!lastError || lastError === 'Hash mismatch') {
            const cachedBinaryUri = `${nftId}_${uri}`;
            setContentCache({
              binary: Buffer.from(cachedBinaryUri).toString('base64'),
              valid: !lastError,
            });
            setThumbnail({ binary: `cached://${cachedBinaryUri}` });
          }
        }
        setIsValid(!lastError);
      }
      if (lastError) {
        setError(lastError);
      }
    }
    setIsLoading(false);
    setIsValidationProcessed(true);
  }

  function checkBinaryCache() {
    if (contentCache.binary) {
      setThumbnail({
        binary: `cached://${Buffer.from(
          contentCache.binary,
          'base64',
        ).toString()}`,
      });
      if (contentCache.valid === false) {
        lastError = 'Hash mismatch';
      }
    }
  }

  useEffect(() => {
    if (uri) {
      if (metadata && !metadataError && (isPreview || isAudio(uri))) {
        validateHash(metadata);
      } else if (isImage(uri) || validateNFT) {
        validateHash({});
      } else if (!isPreview) {
        checkBinaryCache();
      } else {
        setIsLoading(false);
        setIsValid(true);
      }
    } else {
      setIsValid(false);
    }
  }, [metadata, uri, ignoreSizeLimit, forceReloadNFT, validateNFT]);

  return {
    isValid,
    isLoading: isPreview ? isLoading : false,
    error,
    thumbnail,
    isValidationProcessed,
    validateNFT,
    encoding,
  };
}
