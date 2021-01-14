import React, { ReactElement } from 'react';
import styled from 'styled-components';
import { Help as HelpIcon } from '@material-ui/icons';
import { Tooltip } from '@material-ui/core';

const StyledHelpIcon = styled(HelpIcon)`
  color: ${({ theme }) =>
    theme.palette.type === 'dark' ? 'white' : '#757575'};
  font-size: 1rem;
`;

type Props = {
  children?: ReactElement<any>;
  interactive?: boolean;
};

export default function TooltipIcon(props: Props) {
  const { children, interactive } = props;
  if (!children) {
    return null;
  }

  return (
    <Tooltip title={children} interactive={interactive} arrow>
      <StyledHelpIcon color="disabled" />
    </Tooltip>
  );
}

TooltipIcon.defaultProps = {
  children: undefined,
};