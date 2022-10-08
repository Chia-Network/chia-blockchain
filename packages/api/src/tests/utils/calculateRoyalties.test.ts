import BigNumber from 'bignumber.js';
import {
  NFTInfo,
  RoyaltyCalculationFungibleAsset,
  RoyaltyCalculationRoyaltyAsset,
} from '../../@types';
import royaltyAssetFromNFTInfo, {
  fungibleAssetFromAssetIdAndAmount,
  fungibleAssetFromWalletIdAndAmount,
} from '../../utils/calculateRoyalties';

describe('calculateRoyalties', () => {
  describe('#royaltyAssetFromNFTInfo', () => {
    const exampleNFT: NFTInfo = {
      chainInfo: '',
      dataHash: '',
      dataUris: [],
      editionNumber: 0,
      editionTotal: 0,
      launcherId: '',
      launcherPuzhash: '',
      licenseHash: '',
      licenseUris: [],
      metadataHash: '',
      metadataUris: [],
      mintHeight: 0,
      minterDid: '',
      nftCoinId: '',
      ownerDid: '',
      ownerPubkey: '',
      pendingTransaction: 0,
      royaltyPercentage: 350,
      royaltyPuzzleHash:
        '0xf6c2a79af727bfada9fc8fa6eaa57189c6a5ad4407333e573d1e08293817d5ad',
      supportsDid: false,
      updaterPuzhash: '',
      walletId: undefined,
      $nftId: 'nft1g9xfeujpq402dhxrms5wqvh73rr02remvwvycr9s4cxzzlkg324s3nu8vj',
    };

    it('converts mainnet NFTInfo to a RoyaltyCalculationRoyaltyAsset object', () => {
      const royaltyAsset: RoyaltyCalculationRoyaltyAsset =
        royaltyAssetFromNFTInfo(exampleNFT, false);
      expect(royaltyAsset.asset).toBe(
        'nft1g9xfeujpq402dhxrms5wqvh73rr02remvwvycr9s4cxzzlkg324s3nu8vj'
      );
      expect(royaltyAsset.royaltyAddress).toBe(
        'xch17mp20xhhy7l6m20u37nw4ft338r2tt2yquenu4earcyzjwqh6kksc8dyjc'
      );
      expect(royaltyAsset.royaltyPercentage).toBe(350);
    });
    it('converts testnet NFTInfo to a RoyaltyCalculationRoyaltyAsset object', () => {
      const royaltyAsset: RoyaltyCalculationRoyaltyAsset =
        royaltyAssetFromNFTInfo(exampleNFT, true);
      expect(royaltyAsset.asset).toBe(
        'nft1g9xfeujpq402dhxrms5wqvh73rr02remvwvycr9s4cxzzlkg324s3nu8vj'
      );
      expect(royaltyAsset.royaltyAddress).toBe(
        'txch17mp20xhhy7l6m20u37nw4ft338r2tt2yquenu4earcyzjwqh6kks4q2jnt'
      );
      expect(royaltyAsset.royaltyPercentage).toBe(350);
    });
  });
  describe('#fungibleAssetFromWalletIdAndAmount', () => {
    it('converts an numeric wallet id and amount to a fungible asset', () => {
      const fungibleAsset: RoyaltyCalculationFungibleAsset =
        fungibleAssetFromWalletIdAndAmount(
          1,
          new BigNumber(100_000_000_000_000)
        );
      expect(fungibleAsset.asset).toBe('1');
      expect(fungibleAsset.amount).toEqual(new BigNumber(100_000_000_000_000));
    });
    it('converts a string wallet id and amount to a fungible asset', () => {
      const fungibleAsset: RoyaltyCalculationFungibleAsset =
        fungibleAssetFromWalletIdAndAmount('2', new BigNumber(100_000));
      expect(fungibleAsset.asset).toBe('2');
      expect(fungibleAsset.amount).toEqual(new BigNumber(100_000));
    });
  });
  describe('#fungibleAssetFromAssetIdAndAmount', () => {
    it('converts an asset id and amount to a fungible asset', () => {
      const fungibleAsset: RoyaltyCalculationFungibleAsset =
        fungibleAssetFromAssetIdAndAmount(
          'a628c1c2c6fcb74d53746157e438e108eab5c0bb3e5c80ff9b1910b3e4832913',
          new BigNumber(100_000_000_000_000)
        );
      expect(fungibleAsset.asset).toBe(
        'a628c1c2c6fcb74d53746157e438e108eab5c0bb3e5c80ff9b1910b3e4832913'
      );
      expect(fungibleAsset.amount).toEqual(new BigNumber(100_000_000_000_000));
    });
  });
});
