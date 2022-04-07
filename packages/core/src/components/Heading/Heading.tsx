import React from 'react';
import { Typography, type TypographyProps } from '@mui/material';

function getMuiVariant(variant: string): TypographyProps['variant'] {
  switch (variant) {
    case 'TITLE':
      return 'h5';
    case 'SUBTITLE':
      return 'h6';
    default:
      return 'h5';
  }
}

export type HeadingProps = TypographyProps & {
  variant?: 'TITLE' | 'SUBTITLE';
};

export default function Heading(props: HeadingProps) {
  const { variant = 'TITLE', ...rest } = props;

  return (
    <Typography variant={getMuiVariant(variant)} {...rest} />
  );
}
