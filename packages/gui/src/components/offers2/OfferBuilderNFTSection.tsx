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
  muted?: boolean;
  viewer?: boolean;
  isMyOffer?: boolean;
};

export default function OfferBuilderNFTSection(
  props: OfferBuilderNFTSectionProps,
) {
  const { name, offering, muted, viewer, isMyOffer = false } = props;

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

  const showProvenance = viewer
    ? isMyOffer
      ? offering
      : !offering
    : !offering;
  const showRoyalties = viewer ? (isMyOffer ? !offering : offering) : offering;

  return (
    <OfferBuilderSection
      icon={<NFTs />}
      title={<Trans>NFT</Trans>}
      subtitle={<Trans>One-of-a-kind Collectible assets</Trans>}
      onAdd={handleAdd}
      expanded={!!fields.length}
      muted={muted}
    >
      <Flex gap={4} flexDirection="column">
        {fields.map((field, index) => (
          <OfferBuilderNFT
            key={field.id}
            name={`${name}.${index}`}
            provenance={showProvenance}
            showRoyalties={showRoyalties}
            onRemove={() => handleRemove(index)}
          />
        ))}
      </Flex>
    </OfferBuilderSection>
  );
}
