import React, { type ReactNode } from 'react';
import { Typography } from '@mui/material';

export type SettingsLabelProps = {
  children?: ReactNode;
};

export default function SettingsLabel(props: SettingsLabelProps) {
  const { children } = props;

  return (
    <Typography variant="body1">
      {children}
    </Typography>
  );
}
