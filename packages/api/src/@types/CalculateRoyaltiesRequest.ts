import RoyaltyCalculationRoyaltyAsset from './RoyaltyCalculationRoyaltyAsset';
import RoyaltyCalculationFungibleAsset from './RoyaltyCalculationFungibleAsset';

type CalculateRoyaltiesRequest = {
  royaltyAssets: RoyaltyCalculationRoyaltyAsset[];
  fungibleAssets: RoyaltyCalculationFungibleAsset[];
};

export default CalculateRoyaltiesRequest;
