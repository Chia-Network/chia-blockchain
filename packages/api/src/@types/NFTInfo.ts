type NFTInfo = {
  launcherId: string;
  launcherPuzhash: string;
  nftCoinId: string;
  didOwner: string;
  royalty: number;
  dataUris: string[];
  dataHash: string;
  metadataUris: string[];
  metadataHash: string;
  licenseUris: string[];
  licenseHash: string;
  pendingTransaction: number;
  seriesNumber: number;
  seriesTotal: number;
  chainInfo: string;
  updaterPuzhash: string;

  // Properties added by the frontend
  walletId: number | undefined;
  $nftId: string; // bech32m-encoding of the launcherId e.g. nft1eryfv3va6lftjslhq3jhyx30dk8wtsfd8epseuq3rnlf2tavpjmsq0ljcv
};

export default NFTInfo;
