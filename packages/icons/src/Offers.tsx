import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import OffersIcon from './images/Offers.svg';
import OffersSmallIcon from './images/OffersSmall.svg';

export function OffersSmall(props: SvgIconProps) {
  return <SvgIcon component={OffersSmallIcon} viewBox="0 0 18 18" {...props} />;
}

export default function Offers(props: SvgIconProps) {
  return <SvgIcon component={OffersIcon} viewBox="0 0 32 32" {...props} />;
}
