import BigNumber from 'bignumber.js';

type RoyaltyCalculationFungibleAsset = {
  asset: string; // Use walletId value here. Corresponds to RoyaltyCalculationFungibleAssetPayout.asset
  amount: BigNumber;
};

export default RoyaltyCalculationFungibleAsset;
