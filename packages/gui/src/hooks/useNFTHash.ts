import useVerifyHash from './useVerifyHash';
import { mimeTypeRegex } from '../util/utils.js';

function isAudio(uri: string) {
  return mimeTypeRegex(uri, /^audio/);
}

function isVideo(uri: string) {
  return mimeTypeRegex(uri, /^video/);
}

export default function useNFTHash(
  nft: any,
  ignoreSizeLimit: boolean = false,
  isPreview: boolean,
  metadata: any,
  metadataError: any,
) {
  const { dataUris } = nft;
  let uri = dataUris?.[0];

  let { isValid, isLoading, thumbnail, error } = useVerifyHash(
    uri,
    ignoreSizeLimit,
    metadata,
    metadataError,
    isPreview,
    nft.dataHash,
  );

  thumbnail.type = isVideo(uri) ? 'video' : isAudio(uri) ? 'audio' : 'unknown';

  if (!isPreview) {
    error = undefined;
  }

  return {
    isValid,
    isLoading,
    thumbnail,
    error,
  };
}
