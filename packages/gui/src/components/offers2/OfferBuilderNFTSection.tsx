import React from 'react';
import { Trans } from '@lingui/macro';
import { NFTs } from '@chia/icons';
import { Flex } from '@chia/core';
import { useFieldArray } from 'react-hook-form';
import OfferBuilderSection from './OfferBuilderSection';
import OfferBuilderNFT from './OfferBuilderNFT';

export type OfferBuilderNFTSectionProps = {
  name: string;
  offering?: boolean;
};

export default function OfferBuilderNFTSection(
  props: OfferBuilderNFTSectionProps,
) {
  const { name, offering = false } = props;

  const { fields, append, remove } = useFieldArray({
    name,
  });

  function handleAdd() {
    append({
      nftId: '',
    });
  }

  function handleRemove(index: number) {
    remove(index);
  }

  return (
    <OfferBuilderSection
      icon={<NFTs />}
      title={<Trans>NFT</Trans>}
      subtitle={<Trans>One-of-a-kind Collectible assets</Trans>}
      onAdd={handleAdd}
      expanded={!!fields.length}
    >
      <Flex gap={4} flexDirection="column">
        {fields.map((field, index) => (
          <OfferBuilderNFT
            key={field.id}
            name={`${name}.${index}`}
            provenance={!offering}
            onRemove={() => handleRemove(index)}
          />
        ))}
      </Flex>
    </OfferBuilderSection>
  );
}
