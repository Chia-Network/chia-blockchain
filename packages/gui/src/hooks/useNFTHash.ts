import { type NFTInfo } from '@chia/api';
import useVefifyURIHash from './useVefifyURIHash';

export default function useNFTHash(nft: NFTInfo) {
  const { dataHash, dataUris } = nft;
  const uri = dataUris?.[0];

  return useVefifyURIHash(uri, dataHash);
}
