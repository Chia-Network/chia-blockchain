import React from 'react';
import { SvgIcon, SvgIconProps } from '@material-ui/core';
import { ReactComponent as SettingsIcon } from './images/settings.svg';

export default function Settings(props: SvgIconProps) {
  return <SvgIcon component={SettingsIcon} viewBox="0 0 32 32" {...props} />;
}
