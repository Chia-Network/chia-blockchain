import React from 'react';
import { Back } from '@chia/core';
import { Typography } from '@mui/material';
import type { Variant } from '@mui/material/styles/createTypography';

type Props = {
  title: string | React.ReactNode;
  titleVariant?: Variant;
  referrerPath?: string;
};

export default function OfferNavigationHeader(props: Props): JSX.Element {
  const { title, titleVariant = 'h5', referrerPath, ...rest } = props;

  return referrerPath ? (
    <Back to={referrerPath} variant={titleVariant} {...rest}>
      {title}
    </Back>
  ) : (
    <Typography variant={titleVariant}>{title}</Typography>
  );
}
