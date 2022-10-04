import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import FeesIcon from './images/Fees.svg';

export default function Fees(props: SvgIconProps) {
  return <SvgIcon component={FeesIcon} viewBox="0 0 32 32" {...props} />;
}
