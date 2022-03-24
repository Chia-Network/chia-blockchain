import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import OffersIcon from './images/Offers.svg';

export default function Offers(props: SvgIconProps) {
  return <SvgIcon component={OffersIcon} viewBox="0 0 34 34" {...props} />;
}
