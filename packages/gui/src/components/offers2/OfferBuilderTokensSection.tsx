import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { Tokens } from '@chia/icons';
import { Flex } from '@chia/core';
import { WalletType } from '@chia/api';
import type { Wallet } from '@chia/api';
import { useGetWalletsQuery } from '@chia/api-react';
import { useFieldArray, useWatch } from 'react-hook-form';
import OfferBuilderSection from './OfferBuilderSection';
import OfferBuilderToken from './OfferBuilderToken';

export type OfferBuilderTokensSectionProps = {
  name: string;
  offering?: boolean;
  muted?: boolean;
};

export default function OfferBuilderTokensSection(
  props: OfferBuilderTokensSectionProps,
) {
  const { name, offering, muted } = props;

  const { data: wallets } = useGetWalletsQuery();
  const { fields, append, remove } = useFieldArray({
    name,
  });

  const tokens = useWatch({
    name,
  });

  function handleAdd() {
    append({
      amount: '',
      assetId: '',
    });
  }

  function handleRemove(index: number) {
    remove(index);
  }

  const usedAssets = tokens.map((field) => field.assetId);
  const showAdd = useMemo(() => {
    if (!wallets) {
      return false;
    }

    const catWallets = wallets.filter(
      (wallet: Wallet) => wallet.type === WalletType.CAT,
    );
    return catWallets.length > tokens.length;
  }, [wallets, tokens]);

  return (
    <OfferBuilderSection
      icon={<Tokens />}
      title={<Trans>Tokens</Trans>}
      subtitle={
        <Trans>Chia Asset Tokens (CATs) are tokens built on top of XCH</Trans>
      }
      onAdd={showAdd ? handleAdd : undefined}
      expanded={!!fields.length}
      muted={muted}
    >
      <Flex gap={4} flexDirection="column">
        {fields.map((field, index) => (
          <OfferBuilderToken
            key={field.id}
            usedAssets={usedAssets}
            name={`${name}.${index}`}
            onRemove={() => handleRemove(index)}
            hideBalance={!offering}
          />
        ))}
      </Flex>
    </OfferBuilderSection>
  );
}
