import { useState, useEffect } from 'react';
import type { NFTInfo } from '@chia/api';
import { useLocalStorage } from '@chia/core';
import isURL from 'validator/lib/isURL';

import getRemoteFileContent from '../util/getRemoteFileContent';
import { MAX_FILE_SIZE } from './useNFTMetadata';
import { mimeTypeRegex, isImage, parseExtensionFromUrl } from '../util/utils';
import { FileType } from '../util/getRemoteFileContent';

import computeHash from '../util/computeHash';

const ipcRenderer = (window as any).ipcRenderer;

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
  isLoadingMetadata: boolean;
};

let encoding: string = 'binary';

export default function useVerifyHash(props: VerifyHash): {
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
    isLoadingMetadata,
  } = props;
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

    if (metadata.preview_video_uris && !metadata.preview_video_hash) {
      setIsLoading(false);
      lastError = 'missing preview_video_hash';
    } else if (metadata.preview_image_uris && !metadata.preview_image_hash) {
      setIsLoading(false);
      lastError = 'missing preview_image_hash';
    } else {
      /* ================== VIDEO THUMBNAIL ================== */
      if (metadata['preview_video_uris']) {
        /* if it's cached, don't try to validate hash at all */
        if (thumbCache.video) {
          setThumbnail({
            video: `cached://${thumbCache.video}`,
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
                lastError = 'Invalid URI';
              }
              const { isValid, wasCached } = await getRemoteFileContent({
                uri: videoUri,
                forceCache: true,
                nftId,
                type: FileType.Video,
                dataHash: metadata['preview_video_hash'],
              });
              if (!isValid) {
                lastError = 'thumbnail hash mismatch';
              }
              if (isValid) {
                videoThumbValid = true;
                const cachedUri = `${nftId}_${videoUri}`;
                setThumbnail({
                  video: wasCached
                    ? `cached://${computeHash(cachedUri, {
                        encoding: 'utf-8',
                      })}`
                    : videoUri,
                });
                if (wasCached) {
                  setThumbCache({
                    video: computeHash(cachedUri, { encoding: 'utf-8' }),
                    time: new Date().getTime(),
                  });
                }
                setIsLoading(false);
                lastError = null;
                break;
              }
            } catch (e: any) {
              /* if we already found content that is hash mismatched, show mismatch error! */
              lastError = lastError || 'failed fetch content';
            }
          }
        }
      }

      /* ================== IMAGE THUMBNAIL ================== */
      if (metadata['preview_image_uris'] && !videoThumbValid) {
        uris = metadata['preview_image_uris'];
        for (let i = 0; i < uris.length; i++) {
          const imageUri = uris[i];
          /* if it's cached, don't try to validate hash at all */
          if (thumbCache.image) {
            lastError = null;
            setThumbnail({
              image: `cached://${thumbCache.image}`,
            });
            setIsLoading(false);
            imageThumbValid = true;
            break;
          }
          try {
            if (!isURL(imageUri)) {
              lastError = 'Invalid URI';
            }
            const { wasCached, isValid } = await getRemoteFileContent({
              uri: imageUri,
              forceCache: true,
              nftId,
              dataHash: metadata['preview_image_hash'],
              type: FileType.Image,
            });
            if (!isValid) {
              lastError = 'thumbnail hash mismatch';
            }
            if (isValid) {
              imageThumbValid = true;
              const cachedImageUri = `${nftId}_${imageUri}`;
              if (wasCached) {
                setThumbCache({
                  image: computeHash(cachedImageUri, { encoding: 'utf-8' }),
                  time: new Date().getTime(),
                });
              }
              setThumbnail({
                image: wasCached
                  ? `cached://${computeHash(cachedImageUri, {
                      encoding: 'utf-8',
                    })}`
                  : imageUri,
              });
              setIsLoading(false);
              break;
            }
          } catch (e: any) {
            /* if we already found content that is hash mismatched, show mismatch error! */
            lastError = lastError || 'failed fetch content';
          }
        }
      }

      /* ================== BINARY CONTENT ================== */
      if (isImage(uri) || !isPreview) {
        let showCachedUri: boolean = false;
        if (contentCache.valid !== undefined && contentCache.binary) {
          if (parseExtensionFromUrl(uri) === 'svg') {
            const svgContent = await ipcRenderer.invoke(
              'getSvgContent',
              contentCache.binary,
            );
            if (svgContent) {
              setThumbnail({
                binary: svgContent,
              });
              if (contentCache.valid === false) {
                lastError = lastError || 'Hash mismatch';
              }
            }
          } else {
            const thumbnailExists = videoThumbValid || imageThumbValid;
            checkBinaryCache({ lastError, thumbnailExists });
          }
        } else {
          let dataContent;
          try {
            const {
              data,
              encoding: fileEncoding,
              wasCached,
              isValid,
            } = await getRemoteFileContent({
              uri,
              maxSize:
                ignoreSizeLimit || validateNFT ? Infinity : MAX_FILE_SIZE,
              forceCache: true,
              nftId,
              type: FileType.Binary,
              dataHash,
            });

            dataContent = data;

            showCachedUri = wasCached;

            encoding = fileEncoding;

            if (!isValid) {
              lastError = lastError || 'Hash mismatch';
            }
          } catch (e: any) {
            lastError = lastError || e.message;
          }

          /* show binary content even though the hash is mismatched! */
          if (!lastError || lastError === 'Hash mismatch') {
            const cachedBinaryUri = `${nftId}_${uri}`;
            setContentCache({
              nftId,
              binary: showCachedUri
                ? computeHash(cachedBinaryUri, { encoding: 'utf-8' })
                : null,
              valid: !lastError,
              time: new Date().getTime(),
            });
            if (parseExtensionFromUrl(uri) === 'svg' && dataContent) {
              setThumbnail({
                binary: dataContent,
              });
            }
          }
        }
      }
    }
    if (lastError) {
      setError(lastError);
    }
    setIsLoading(false);
    setIsValidationProcessed(true);
  }

  function checkBinaryCache({ lastError, thumbnailExists }) {
    if (contentCache.binary) {
      if (!thumbnailExists) {
        setThumbnail({
          binary: `cached://${contentCache.binary}`,
        });
      }
      if (contentCache.valid === false) {
        lastError = lastError || 'Hash mismatch';
      }
    }
  }

  useEffect(() => {
    if (!isLoadingMetadata) {
      if (
        metadata &&
        Object.keys(metadata).length > 0 &&
        !metadataError &&
        (isPreview || isAudio(uri))
      ) {
        validateHash(metadata);
      } else if (isImage(uri) || validateNFT) {
        validateHash({});
      } else if (!isPreview) {
        checkBinaryCache({});
      } else {
        setIsLoading(false);
      }
    }
  }, [isLoadingMetadata, uri, ignoreSizeLimit, forceReloadNFT, validateNFT]);

  return {
    isLoading: isPreview ? isLoading : false,
    error,
    thumbnail,
    isValidationProcessed,
    validateNFT,
    encoding,
  };
}
