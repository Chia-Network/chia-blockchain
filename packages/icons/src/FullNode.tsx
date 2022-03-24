import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import FullNodeIcon from './images/FullNode.svg';

export default function FullNode(props: SvgIconProps) {
  return <SvgIcon component={FullNodeIcon} viewBox="0 0 36 36" {...props} />;
}
