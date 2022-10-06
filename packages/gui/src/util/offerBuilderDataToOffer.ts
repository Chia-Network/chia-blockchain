import type { Wallet } from '@chia/api';
import { WalletType } from '@chia/api';
import { t } from '@lingui/macro';
import { chiaToMojo, catToMojo } from '@chia/core';
import BigNumber from 'bignumber.js';
import type OfferBuilderData from '../@types/OfferBuilderData';
import findCATWalletByAssetId from './findCATWalletByAssetId';
import { prepareNFTOfferFromNFTId } from './prepareNFTOffer';
import type Driver from '../@types/Driver';

// Amount exceeds spendable balance
export default async function offerBuilderDataToOffer(
  data: OfferBuilderData,
  wallets: Wallet[],
  validateOnly?: boolean,
): Promise<{
  walletIdsAndAmounts?: Record<string, BigNumber>;
  driverDict?: Record<string, any>;
  feeInMojos: BigNumber;
  validateOnly?: boolean;
}> {
  const {
    offered: {
      xch: offeredXch = [],
      tokens: offeredTokens = [],
      nfts: offeredNfts = [],
      fee: [firstFee] = [],
    },
    requested: {
      xch: requestedXch = [],
      tokens: requestedTokens = [],
      nfts: requestedNfts = [],
    },
  } = data;

  const feeInMojos = firstFee ? chiaToMojo(firstFee.amount) : new BigNumber(0);

  const walletIdsAndAmounts: Record<string, BigNumber> = {};
  const driverDict: Record<string, Driver> = {};

  const hasOffer =
    !!offeredXch.length || !!offeredTokens.length || !!offeredNfts.length;
  const hasRequest =
    !!requestedXch.length || !!requestedTokens.length || !!requestedNfts.length;

  if (!hasOffer && !hasRequest) {
    throw new Error(t`Offer or request must be specified`);
  }

  offeredXch.forEach((xch) => {
    const { amount } = xch;
    if (!amount) {
      throw new Error(t`Please enter an amount for each row`);
    }

    const wallet = wallets.find((w) => w.type === WalletType.STANDARD_WALLET);
    if (!wallet) {
      throw new Error(t`No standard wallet found`);
    }

    walletIdsAndAmounts[wallet.id] = chiaToMojo(amount).negated();
  });

  offeredTokens.forEach((token) => {
    const { assetId, amount } = token;

    if (!assetId) {
      throw new Error(t`Please select an asset for each row`);
    }

    if (!amount) {
      throw new Error(t`Please enter an amount for each row`);
    }

    const wallet = findCATWalletByAssetId(wallets, assetId);
    if (!wallet) {
      throw new Error(t`No CAT wallet found for assetId ${assetId}`);
    }

    walletIdsAndAmounts[wallet.id] = catToMojo(amount).negated();
  });

  await Promise.all(
    offeredNfts.map(async ({ nftId }) => {
      const { id, amount, driver } = await prepareNFTOfferFromNFTId(
        nftId,
        true,
      );

      walletIdsAndAmounts[id] = amount;
      if (driver) {
        driverDict[id] = driver;
      }
    }),
  );

  // requested
  requestedXch.forEach((xch) => {
    const { amount } = xch;
    if (!amount) {
      throw new Error(t`Please enter an amount for each row`);
    }

    const wallet = wallets.find((w) => w.type === WalletType.STANDARD_WALLET);
    if (!wallet) {
      throw new Error(t`No standard wallet found`);
    }

    if (wallet.id in walletIdsAndAmounts) {
      throw new Error(t`Cannot offer and request the same asset`);
    }

    walletIdsAndAmounts[wallet.id] = chiaToMojo(amount);
  });

  requestedTokens.forEach((token) => {
    const { assetId, amount } = token;

    if (!assetId) {
      throw new Error(t`Please select an asset for each row`);
    }

    if (!amount) {
      throw new Error(t`Please enter an amount for each row`);
    }

    const wallet = findCATWalletByAssetId(wallets, assetId);
    if (!wallet) {
      throw new Error(t`No CAT wallet found for assetId ${assetId}`);
    }

    walletIdsAndAmounts[wallet.id] = catToMojo(amount);
  });

  await Promise.all(
    requestedNfts.map(async ({ nftId }) => {
      const { id, amount, driver } = await prepareNFTOfferFromNFTId(
        nftId,
        false,
      );

      walletIdsAndAmounts[id] = amount;
      if (driver) {
        driverDict[id] = driver;
      }
    }),
  );

  return {
    walletIdsAndAmounts,
    driverDict,
    feeInMojos,
    validateOnly,
  };
}
