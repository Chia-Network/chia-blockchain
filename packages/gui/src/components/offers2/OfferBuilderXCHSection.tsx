import React from 'react';
import { Trans } from '@lingui/macro';
import { useFieldArray } from 'react-hook-form';
import { Farming } from '@chia/icons';
import { Loading, useCurrencyCode } from '@chia/core';
import OfferBuilderSection from './OfferBuilderSection';
import OfferBuilderWalletAmount from './OfferBuilderWalletAmount';
import useStandardWallet from '../../hooks/useStandardWallet';

export type OfferBuilderXCHSectionProps = {
  name: string;
};

export default function OfferBuilderXCHSection(
  props: OfferBuilderXCHSectionProps,
) {
  const { name } = props;
  const { wallet, loading } = useStandardWallet();
  const currencyCode = useCurrencyCode();
  const { fields, append, remove } = useFieldArray({
    name,
  });

  function handleAdd() {
    if (!fields.length) {
      append({
        amount: '',
      });
    }
  }

  function handleRemove(index: number) {
    remove(index);
  }

  return (
    <OfferBuilderSection
      icon={<Farming />}
      title={currencyCode}
      subtitle={
        <Trans>
          Chia ({currencyCode}) is a digital currency that is secure and
          sustainable
        </Trans>
      }
      onAdd={!fields.length ? handleAdd : undefined}
      expanded={!!fields.length}
    >
      {loading ? (
        <Loading />
      ) : (
        fields.map((field, index) => (
          <OfferBuilderWalletAmount
            key={field.id}
            walletId={wallet.id}
            name={`${name}.${index}.amount`}
            onRemove={() => handleRemove(index)}
          />
        ))
      )}
    </OfferBuilderSection>
  );
}
