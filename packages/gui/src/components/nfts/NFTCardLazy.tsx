import React, { useRef } from 'react';
import NFTCard, { type NFTCardProps } from './NFTCard';
import useIntersectionObserver from '../../hooks/useIntersectionObserver';
import { Box, Card } from '@mui/material';

export type NFTCardLazyProps = NFTCardProps & {
  minHeight?: number;
};

export default function NFTCardLazy(props: NFTCardLazyProps) {
  const { minHeight = 300, ...rest } = props;
  const cardRef = useRef();
  const entry = useIntersectionObserver(cardRef, {
    freezeOnceVisible: true,
  });

  const isVisible = !!entry?.isIntersecting;

  return (
    <Box minHeight={isVisible ? undefined : `${minHeight}px`} ref={cardRef}>
      {isVisible
        ? <NFTCard {...rest} />
        : <Card />}
    </Box>
  );
}
