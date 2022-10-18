import Response from './Response';
import RoyaltyCalculationFungibleAssetPayout from './RoyaltyCalculationFungibleAssetPayout';

type CalculateRoyaltiesResponse = Response & {
  [key: string]: RoyaltyCalculationFungibleAssetPayout[];
};

export default CalculateRoyaltiesResponse;
