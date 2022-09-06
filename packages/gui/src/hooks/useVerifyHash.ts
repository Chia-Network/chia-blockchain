import { useState, useEffect } from 'react';
import isURL from 'validator/lib/isURL';

import isContentHashValid from '../util/isContentHashValid';
import getRemoteFileContent from '../util/getRemoteFileContent';
import { MAX_FILE_SIZE } from './useVerifyURIHash';
import { mimeTypeRegex } from '../util/utils.js';

function isAudio(uri: string) {
  return mimeTypeRegex(uri, /^audio/);
}

function isImage(uri: string) {
  return mimeTypeRegex(uri, /^image/) || mimeTypeRegex(uri, /^$/);
}

export default function useVerifyHash(
  uri: string,
  ignoreSizeLimit: boolean,
  metadata: any,
  metadataError: any,
  isPreview: boolean,
  dataHash: string,
): {
  isValid: boolean;
  isLoading: boolean;
  error: string | undefined;
  thumbnail: any;
} {
  const [isValid, setIsValid] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [thumbnail, setThumbnail] = useState({});

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
        uris = metadata['preview_video_uris'];
        for (let i = 0; i < uris.length; i++) {
          const uri = uris[i];
          try {
            if (!isURL(uri)) {
              setError('Invalid URI');
            }
            const { data: content, encoding } = await getRemoteFileContent(
              uri,
              ignoreSizeLimit ? undefined : MAX_FILE_SIZE,
            );
            const hash = metadata['preview_video_hash'];
            const isHashValid = isContentHashValid(content, hash, encoding);
            if (!isHashValid) {
              lastError = 'thumbnail hash mismatch';
            }
            videoThumbValid = isHashValid;
          } catch (e: any) {
            /* if we already found content that is hash mismatched, show mismatch error! */
            lastError = lastError || 'failed fetch content';
          }
          if (videoThumbValid) {
            setError(undefined);
            setThumbnail({ video: uri });
            setIsLoading(false);
            return;
          }
        }
        if (lastError) {
          setError(lastError);
        }
      }

      if (metadata['preview_image_uris'] && !videoThumbValid) {
        uris = metadata['preview_image_uris'];
        for (let i = 0; i < uris.length; i++) {
          const uri = uris[i];
          try {
            if (!isURL(uri)) {
              setError('Invalid URI');
            }
            const { data: content, encoding } = await getRemoteFileContent(
              uri,
              ignoreSizeLimit ? undefined : MAX_FILE_SIZE,
            );
            const hash = metadata['preview_image_hash'];
            const isHashValid = isContentHashValid(content, hash, encoding);
            if (!isHashValid) {
              lastError = 'thumbnail hash mismatch';
            }
            imageThumbValid = isHashValid;
          } catch (e: any) {
            /* if we already found content that is hash mismatched, show mismatch error! */
            lastError = lastError || 'failed fetch content';
          }
          if (imageThumbValid) {
            setError(undefined);
            setThumbnail({ image: uri });
            setIsLoading(false);
            return;
          }
        }
      }
      if (isImage(uri)) {
        try {
          const { data: content, encoding } = await getRemoteFileContent(
            uri,
            ignoreSizeLimit ? undefined : MAX_FILE_SIZE,
          );
          const isHashValid = isContentHashValid(content, dataHash, encoding);
          if (!isHashValid) {
            lastError = 'Hash mismatch';
          }
        } catch (e: any) {
          setError(e.message);
        }
      }
      if (lastError) {
        setError(lastError);
      }
    }
    setIsLoading(false);
  }

  useEffect(() => {
    if (metadata && !metadataError && (isPreview || isAudio(uri))) {
      validateHash(metadata);
    } else if (isImage(uri)) {
      validateHash({});
    } else {
      setIsLoading(false);
      setIsValid(true);
    }
  }, [metadata, uri, ignoreSizeLimit]);

  return { isValid, isLoading, error, thumbnail };
}
