import React, { type ReactNode } from 'react';
import styled from 'styled-components';
import { Typography } from '@material-ui/core';

const StyledTypography = styled(Typography)`
  text-transform: uppercase;
  font-weight: bold;
  font-size: 0.6875rem;
`;

export type SettingsLabelProps = {
  children?: ReactNode;
};

export default function SettingsLabel(props: SettingsLabelProps) {
  const { children } = props;

  return (
    <StyledTypography variant="body2" color="textSecondary" uppercase>
      {children}
    </StyledTypography>
  );
}
