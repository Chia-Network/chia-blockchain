import React from 'react';
import { SvgIcon, SvgIconProps } from '@mui/material';
import TokensIcon from './images/Tokens.svg';

export default function Tokens(props: SvgIconProps) {
  return <SvgIcon component={TokensIcon} viewBox="0 0 37 28" {...props} />;
}
