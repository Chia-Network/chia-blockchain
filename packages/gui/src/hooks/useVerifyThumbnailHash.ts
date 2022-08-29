import { useState, useEffect } from 'react';
import isURL from 'validator/lib/isURL';
import isContentHashValid from '../util/isContentHashValid';
import getRemoteFileContent from '../util/getRemoteFileContent';
import { MAX_FILE_SIZE } from './useVerifyURIHash';

export default function useVerifyThumbnailHash(
  metadataJson: any,
  isPreview: boolean,
  isAudio: boolean,
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

  async function validateHash(metadataJson: any): Promise<void> {
    let uris: string[] = [];
    let videoThumbValid: boolean = false;
    let imageThumbValid: boolean = false;

    setError(undefined);

    setIsLoading(true);
    setIsValid(false);

    if (metadataJson.preview_video_uris && !metadataJson.preview_video_hash) {
      setIsLoading(false);
      setIsValid(false);
      setError('missing preview_video_hash');
    } else if (
      metadataJson.preview_image_uris &&
      !metadataJson.preview_image_hash
    ) {
      setIsLoading(false);
      setIsValid(false);
      setError('missing preview_image_hash');
    } else {
      if (metadataJson['preview_video_uris']) {
        uris = metadataJson['preview_video_uris'];
        for (let i = 0; i < uris.length; i++) {
          const uri = uris[i];
          try {
            if (!isURL(uri)) {
              setError('Invalid URI');
            }
            const { data: content, encoding } = await getRemoteFileContent(
              uri,
              MAX_FILE_SIZE,
            );
            const hash = metadataJson['preview_video_hash'];
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

      if (metadataJson['preview_image_uris'] && !videoThumbValid) {
        uris = metadataJson['preview_image_uris'];
        for (let i = 0; i < uris.length; i++) {
          const uri = uris[i];
          try {
            if (!isURL(uri)) {
              setError('Invalid URI');
            }
            const { data: content, encoding } = await getRemoteFileContent(
              uri,
              MAX_FILE_SIZE,
            );
            const hash = metadataJson['preview_image_hash'];
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
      if (lastError) {
        setError(lastError);
      }
    }
    setIsLoading(false);
  }

  useEffect(() => {
    if ((!metadataJson.error && isPreview) || isAudio) {
      validateHash(metadataJson);
    } else {
      setIsLoading(false);
      setIsValid(true);
    }
  }, [metadataJson]);

  return { isValid, isLoading, error, thumbnail };
}
