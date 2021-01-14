import React from 'react';
import styled from 'styled-components';
import { StateColor } from '@chia/core';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';

const StyledFiberManualRecordIcon = styled(({ color, ...rest }) => <FiberManualRecordIcon {...rest} />)`
  font-size: 1rem;
  color: ${({ color }) => color};
`;

type Props = {
  color: StateColor;
};

export default function Status(props: Props) {
  const { color } = props;

  return (
    <StyledFiberManualRecordIcon color={color} />
  );
}
