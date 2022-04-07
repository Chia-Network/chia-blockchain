import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import FarmingIcon from './images/Farming.svg';

export default function Farming(props: SvgIconProps) {
  return <SvgIcon component={FarmingIcon} viewBox="0 0 32 32" {...props} />;
}
