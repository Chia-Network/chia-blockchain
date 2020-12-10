import React, { ReactNode } from 'react';
import { Paper } from '@material-ui/core';
import styled from 'styled-components';

const StyledPaper = styled(Paper)`
  background-color: #272c34;
  color: white;
  width: 100%;
  height: 40vh;
  padding: ${({ theme }) => `${theme.spacing(1)}px ${theme.spacing(2)}px`};
  overflow: auto;

  pre {
    word-break: break-all;
    white-space: pre-wrap;
  }
`;

type Props = {
  children?: ReactNode;
};

export default function Log(props: Props) {
  const { children } = props;

  return (
    <StyledPaper>
      <pre>{children}</pre>
    </StyledPaper>
  );
}

Log.defaultProps = {
  children: undefined,
};
