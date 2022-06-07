import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import NFTsIcon from './images/NFTs.svg';
import NFTsSmallIcon from './images/NFTsSmall.svg';

export function NFTsSmall(props: SvgIconProps) {
  return <SvgIcon component={NFTsSmallIcon} viewBox="0 0 18 18" {...props} />;
}

export default function NFTs(props: SvgIconProps) {
  return <SvgIcon component={NFTsIcon} viewBox="0 0 38 28" {...props} />;
}
