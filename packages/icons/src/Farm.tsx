import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import FarmIcon from './images/farm.svg';

export default function Farm(props: SvgIconProps) {
  return <SvgIcon component={FarmIcon} viewBox="0 0 32 37" {...props} />;
}
