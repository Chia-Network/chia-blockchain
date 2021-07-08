import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import { ReactComponent as HDDcoinIcon } from './images/hddcoin.svg';

export default function Keys(props: SvgIconProps) {
  return <SvgIcon component={HDDcoinIcon} viewBox="0 0 150 58" {...props} />;
} 