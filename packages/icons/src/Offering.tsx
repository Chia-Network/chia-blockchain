import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import OfferingIcon from './images/Offering.svg';

export default function Offering(props: SvgIconProps) {
  return <SvgIcon component={OfferingIcon} viewBox="0 0 40 40" {...props} />;
}
