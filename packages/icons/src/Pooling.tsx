
import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import PoolingIcon from './images/Pooling.svg';

export default function Pooling(props: SvgIconProps) {
  return <SvgIcon component={PoolingIcon} viewBox="0 0 32 32" {...props} />;
}
