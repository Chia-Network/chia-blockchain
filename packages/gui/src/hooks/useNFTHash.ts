import mime from 'mime-types';
import useVerifyHash from './useVerifyHash';

function mimeTypeRegex(uri: string, regexp: RegExp) {
  const urlOnly = new URL(uri).origin + new URL(uri).pathname;
  const temp = mime.lookup(urlOnly);
  return ((temp || '') as string).match(regexp);
}

function isAudio(uri: string) {
  return mimeTypeRegex(uri, /^audio/);
}

function isVideo(uri: string) {
  return mimeTypeRegex(uri, /^video/);
}

export default function useNFTHash(
  nft: any,
  isPreview: boolean,
  metadata: any,
) {
  const { dataUris } = nft;
  let uri = dataUris?.[0];

  let { isValid, isLoading, thumbnail, error } = useVerifyHash(
    uri,
    metadata,
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
