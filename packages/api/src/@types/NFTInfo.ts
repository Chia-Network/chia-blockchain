type NFTInfo = {
  chainInfo: string;
  dataHash: string;
  dataUris: string[];
  editionNumber: number;
  editionTotal: number;
  launcherId: string;
  launcherPuzhash: string;
  licenseHash: string;
  licenseUris: string[];
  metadataHash: string;
  metadataUris: string[];
  mintHeight: number;
  minterDid: string;
  nftCoinId: string;
  ownerDid: string;
  ownerPubkey: string;
  pendingTransaction: number;
  royaltyPercentage: number; // e.g. 175 == 1.75%
  royaltyPuzzleHash: string;
  supportsDid: boolean;
  updaterPuzhash: string;

  // Properties added by the frontend
  walletId: number | undefined;
  $nftId: string; // bech32m-encoding of the launcherId e.g. nft1eryfv3va6lftjslhq3jhyx30dk8wtsfd8epseuq3rnlf2tavpjmsq0ljcv
};

export default NFTInfo;
