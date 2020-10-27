import React, { ReactElement } from 'react';
import styled from 'styled-components';
import { Help as HelpIcon } from '@material-ui/icons';
import { Tooltip } from '@material-ui/core';

const StyledHelpIcon = styled(HelpIcon)`
  color: rgba(0, 0, 0, 0.54);
  font-size: 1rem;
`;

type Props = {
  value: ReactElement<any>,
};

export default function TooltipIcon(props: Props) {
  const { value } = props;

  return (
    <Tooltip title={value}>
      <StyledHelpIcon />
    </Tooltip>
  );
}
