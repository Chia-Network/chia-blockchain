import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import SettingsIcon from './images/pool.svg';

export default function Settings(props: SvgIconProps) {
  return <SvgIcon component={SettingsIcon} viewBox="0 0 34 34" {...props} />;
}