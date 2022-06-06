type NFTInfo = {
  chainInfo: string;
  dataHash: string;
  dataUris: string[];
  launcherId: string;
  launcherPuzhash: string;
  licenseHash: string;
  licenseUris: string[];
  metadataHash: string;
  metadataUris: string[];
  mintHeight: number;
  nftCoinId: string;
  ownerDid: string;
  ownerPubkey: string;
  pendingTransaction: number;
  royaltyPercentage: number; // e.g. 1750 == 1.75%
  royaltyPuzzleHash: string;
  seriesNumber: number;
  seriesTotal: number;
  supportsDid: boolean;
  updaterPuzhash: string;

  // Properties added by the frontend
  walletId: number | undefined;
  $nftId: string; // bech32m-encoding of the launcherId e.g. nft1eryfv3va6lftjslhq3jhyx30dk8wtsfd8epseuq3rnlf2tavpjmsq0ljcv
};

export default NFTInfo;
