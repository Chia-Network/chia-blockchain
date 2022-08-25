import React, { ReactElement } from 'react';
import styled from 'styled-components';
import { Help as HelpIcon } from '@mui/icons-material';
import { Tooltip } from '@mui/material';

const StyledHelpIcon = styled(HelpIcon)`
  color: ${({ theme }) =>
    theme.palette.mode === 'dark' ? '#c8c8c8' : '#757575'};
  font-size: 1rem;
`;

type Props = {
  children?: ReactElement<any>;
  disableInteractive?: boolean;
};

export default function TooltipIcon(props: Props) {
  const { children, disableInteractive } = props;
  if (!children) {
    return null;
  }

  return (
    <Tooltip title={children} disableInteractive={disableInteractive} arrow>
      <StyledHelpIcon color="disabled" />
    </Tooltip>
  );
}

TooltipIcon.defaultProps = {
  children: undefined,
};
