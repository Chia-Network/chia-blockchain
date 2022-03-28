import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import ChiaIcon from './images/chia.svg';

export default function Keys(props: SvgIconProps) {
  return <SvgIcon component={ChiaIcon} viewBox="0 0 150 58" {...props} />;
}
