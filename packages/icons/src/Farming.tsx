import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import FarmingIcon from './images/Farming.svg';

export default function Farming(props: SvgIconProps) {
  return <SvgIcon component={FarmingIcon} viewBox="0 0 31 34" {...props} />;
}
