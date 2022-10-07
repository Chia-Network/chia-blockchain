import type { NFTInfo } from '@chia/api';
import { store, walletApi } from '@chia/api-react';
import BigNumber from 'bignumber.js';
import { launcherIdFromNFTId } from './nfts';
import type Driver from '../@types/Driver';

export async function prepareNFTOfferFromNFTId(
  nftId: string,
  offeredNFT: boolean,
) {
  const launcherId = launcherIdFromNFTId(nftId);
  if (!launcherId) {
    throw new Error('Invalid NFT ID');
  }

  // Adding a cache subscription
  const resultPromise = store.dispatch(
    walletApi.endpoints.getNFTInfo.initiate({
      coinId: launcherId ?? '',
    }),
  );

  const result = await resultPromise;

  // Removing the corresponding cache subscription
  resultPromise.unsubscribe();

  if (result.error) {
    throw result.error;
  }

  const nft = result.data;
  if (!nft) {
    throw new Error('NFT not found');
  }

  return prepareNFTOffer(nft, offeredNFT);
}

export default function prepareNFTOffer(nft: NFTInfo, offeredNFT: boolean) {
  const driver: Driver = {
    type: 'singleton',
    launcher_id: nft.launcherId,
    launcher_ph: nft.launcherPuzhash,
    also: {
      type: 'metadata',
      metadata: nft.chainInfo,
      updater_hash: nft.updaterPuzhash,
    },
  };

  if (nft.supportsDid) {
    driver.also.also = {
      type: 'ownership',
      owner: '()',
      transfer_program: {
        type: 'royalty transfer program',
        launcher_id: nft.launcherId,
        royalty_address: nft.royaltyPuzzleHash,
        royalty_percentage: `${nft.royaltyPercentage}`,
      },
    };
  }

  const id = launcherIdFromNFTId(nft.$nftId);
  if (!id || `0x${id}` !== nft.launcherId) {
    throw new Error('Invalid NFT ID');
  }

  return {
    nft,
    id,
    amount: offeredNFT ? new BigNumber(-1) : new BigNumber(1),
    driver: !offeredNFT ? driver : undefined,
  };
}
