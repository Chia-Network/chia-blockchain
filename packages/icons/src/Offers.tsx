import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import OffersIcon from './images/Offers.svg';

export default function Offers(props: SvgIconProps) {
  return <SvgIcon component={OffersIcon} viewBox="0 0 32 32" {...props} />;
}
