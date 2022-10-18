import React from 'react';
import { Trans } from '@lingui/macro';
import { Loading } from '@chia/core';
import { Fees } from '@chia/icons';
import { useWallet } from '@chia/wallets';
import { useFieldArray } from 'react-hook-form';
import OfferBuilderSection from './OfferBuilderSection';
import OfferBuilderValue from './OfferBuilderValue';
import useStandardWallet from '../../hooks/useStandardWallet';
import OfferBuilderWalletBalance from './OfferBuilderWalletBalance';

export type OfferBuilderFeeSectionProps = {
  name: string;
  offering?: boolean;
  viewer?: boolean;
};

export default function OfferBuilderFeeSection(
  props: OfferBuilderFeeSectionProps,
) {
  const { name, offering, viewer } = props;
  const { wallet, loading } = useStandardWallet();
  const { unit = '' } = useWallet(wallet?.id);

  const hideBalance = !offering;

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

  const disableReadOnly = offering && viewer;

  return (
    <OfferBuilderSection
      icon={<Fees />}
      title={<Trans>Fees</Trans>}
      subtitle={
        <Trans>Optional network fee to expedite acceptance of your offer</Trans>
      }
      onAdd={!fields.length ? handleAdd : undefined}
      expanded={!!fields.length}
      disableReadOnly={disableReadOnly}
    >
      {loading ? (
        <Loading />
      ) : (
        fields.map((field, index) => (
          <OfferBuilderValue
            key={field.id}
            type="fee"
            label={<Trans>Transaction Speed</Trans>}
            caption={
              !hideBalance && (
                <OfferBuilderWalletBalance walletId={wallet?.id} />
              )
            }
            name={`${name}.${index}.amount`}
            symbol={unit}
            onRemove={() => handleRemove(index)}
            disableReadOnly={disableReadOnly}
          />
        ))
      )}
    </OfferBuilderSection>
  );
}
