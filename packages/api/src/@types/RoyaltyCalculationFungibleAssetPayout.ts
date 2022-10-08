import BigNumber from 'bignumber.js';

type RoyaltyCalculationFungibleAssetPayout = {
  address: string;
  amount: BigNumber;
  asset: string; // Corresponds to RoyaltyCalculationFungibleAsset.asset
};

export default RoyaltyCalculationFungibleAssetPayout;
