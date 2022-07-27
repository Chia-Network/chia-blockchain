import { toBech32m, fromBech32m } from '@chia/api';

export function isValidNFTId(nftId: string): boolean {
  return launcherIdFromNFTId(nftId) !== undefined;
}

export function launcherIdToNFTId(launcherId: string): string {
  return toBech32m(launcherId, 'nft'); // Convert the launcher id to a bech32m encoded nft id
}

export function launcherIdFromNFTId(nftId: string): string | undefined {
  let decoded: string | undefined = undefined;

  try {
    decoded = fromBech32m(nftId);
  } catch (e) {
    return undefined;
  }

  return decoded;
}

export function convertRoyaltyToPercentage(royalty: number): number {
  return royalty / 100;
}
