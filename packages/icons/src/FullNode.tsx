import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import FullNodeIcon from './images/FullNode.svg';

export default function FullNode(props: SvgIconProps) {
  return <SvgIcon component={FullNodeIcon} viewBox="0 0 32 32" {...props} />;
}
