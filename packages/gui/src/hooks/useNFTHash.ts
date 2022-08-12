import type NFTInfo from '@chia/api';
import useVerifyURIHash from './useVerifyURIHash';

export default function useNFTHash(nft: NFTInfo, ignoreSizeLimit = false) {
  const { dataHash, dataUris } = nft;
  const uri = dataUris?.[0];

  return useVerifyURIHash(uri, dataHash, ignoreSizeLimit);
}
