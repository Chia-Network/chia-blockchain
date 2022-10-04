import React from 'react';
import { Trans } from '@lingui/macro';
import { Tokens } from '@chia/icons';
import { Flex } from '@chia/core';
import { useFieldArray, useWatch } from 'react-hook-form';
import OfferBuilderSection from './OfferBuilderSection';
import OfferBuilderToken from './OfferBuilderToken';

export type OfferBuilderTokensSectionProps = {
  name: string;
};

export default function OfferBuilderTokensSection(
  props: OfferBuilderTokensSectionProps,
) {
  const { name } = props;

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

  return (
    <OfferBuilderSection
      icon={<Tokens />}
      title={<Trans>Tokens</Trans>}
      subtitle={
        <Trans>Chia Asset Tokens (CATs) are tokens built on top of XCH</Trans>
      }
      onAdd={handleAdd}
      expanded={!!fields.length}
    >
      <Flex gap={4} flexDirection="column">
        {fields.map((field, index) => (
          <OfferBuilderToken
            key={field.id}
            usedAssets={usedAssets}
            name={`${name}.${index}`}
            onRemove={() => handleRemove(index)}
          />
        ))}
      </Flex>
    </OfferBuilderSection>
  );
}
