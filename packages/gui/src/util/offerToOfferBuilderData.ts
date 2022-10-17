import type { Wallet } from '@chia/api';
import { mojoToCAT, mojoToChia } from '@chia/core';
import BigNumber from 'bignumber.js';
import type OfferBuilderData from '../@types/OfferBuilderData';
import type OfferSummary from '../@types/OfferSummary';
import findCATWalletByAssetId from './findCATWalletByAssetId';
import { launcherIdToNFTId } from '../util/nfts';

export default function offerToOfferBuilderData(
  offerSummary: OfferSummary,
  wallets: Wallet[],
): OfferBuilderData {
  const { fees, offered, requested, infos } = offerSummary;

  const offeredXch: OfferBuilderData['offered']['xch'] = [];
  const offeredTokens: OfferBuilderData['offered']['tokens'] = [];
  const offeredNfts: OfferBuilderData['offered']['nfts'] = [];
  const requestedXch: OfferBuilderData['requested']['xch'] = [];
  const requestedTokens: OfferBuilderData['requested']['tokens'] = [];
  const requestedNfts: OfferBuilderData['requested']['nfts'] = [];

  // processing requested first because it's what you/we will give

  Object.keys(requested).forEach((id) => {
    const amount = new BigNumber(requested[id]);
    const info = infos[id];

    if (info?.type === 'CAT') {
      const wallet = findCATWalletByAssetId(wallets, id);
      if (!wallet) {
        throw new Error('No CAT wallet found');
      }

      offeredTokens.push({
        amount: mojoToCAT(amount).toFixed(),
        assetId: id,
      });
    } else if (info?.type === 'singleton') {
      offeredNfts.push({
        nftId: launcherIdToNFTId(info.launcherId),
      });
    } else if (id === 'xch') {
      offeredXch.push({
        amount: mojoToChia(amount).toFixed(),
      });
    }
  });

  Object.keys(offered).forEach((id) => {
    const amount = new BigNumber(offered[id]);
    const info = infos[id];

    if (info?.type === 'CAT') {
      const wallet = findCATWalletByAssetId(wallets, id);
      if (!wallet) {
        throw new Error('No CAT wallet found');
      }

      requestedTokens.push({
        amount: mojoToCAT(amount).toFixed(),
        assetId: id,
      });
    } else if (info?.type === 'singleton') {
      requestedNfts.push({
        nftId: launcherIdToNFTId(info.launcherId),
      });
    } else if (id === 'xch') {
      requestedXch.push({
        amount: mojoToChia(amount).toFixed(),
      });
    }
  });

  return {
    offered: {
      xch: offeredXch,
      tokens: offeredTokens,
      nfts: offeredNfts,
      fee: [],
    },
    requested: {
      xch: requestedXch,
      tokens: requestedTokens,
      nfts: requestedNfts,
      fee: [
        {
          amount: mojoToChia(fees).toFixed(),
        },
      ],
    },
  };
}
