import BigNumber from 'bignumber.js';
import toBech32m from './toBech32m';
import {
  NFTInfo,
  RoyaltyCalculationFungibleAsset,
  RoyaltyCalculationRoyaltyAsset,
} from '../@types';

export default function royaltyAssetFromNFTInfo(
  nftInfo: NFTInfo,
  testnet = false
): RoyaltyCalculationRoyaltyAsset {
  return {
    asset: nftInfo.$nftId,
    royaltyAddress: toBech32m(
      nftInfo.royaltyPuzzleHash,
      testnet ? 'txch' : 'xch'
    ),
    royaltyPercentage: nftInfo.royaltyPercentage,
  };
}

export function fungibleAssetFromWalletIdAndAmount(
  walletId: number | string,
  amount: BigNumber
): RoyaltyCalculationFungibleAsset {
  return {
    asset: walletId.toString(),
    amount,
  };
}

export function fungibleAssetFromAssetIdAndAmount(
  assetId: string,
  amount: BigNumber
): RoyaltyCalculationFungibleAsset {
  return {
    asset: assetId,
    amount,
  };
}
