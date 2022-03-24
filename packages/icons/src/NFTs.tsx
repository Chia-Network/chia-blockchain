

import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import NFTsIcon from './images/NFTs.svg';

export default function NFTs(props: SvgIconProps) {
  return <SvgIcon component={NFTsIcon} viewBox="0 0 36 26" {...props} />;
}
