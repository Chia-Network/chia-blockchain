import React, { ReactElement, ReactNode } from 'react';
import { Container } from '@material-ui/core';
import styled from 'styled-components';
import DashboardTitle from '../dashboard/DashboardTitle';
import Flex from '../flex/Flex';

const StyledContainer = styled(Container)`
  padding-top: ${({ theme }) => `${theme.spacing(4)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(4)}px`};
`;

type Props = {
  children: ReactElement<any>;
  title?: ReactNode;
};

export default function LayoutMain(props: Props): JSX.Element {
  const { children, title } = props;

  return (
    <>
      <DashboardTitle>{title}</DashboardTitle>
      <Flex
        flexDirection="column"
        flexGrow={1}
        height="100%"
        overflow="auto"
        alignItems="center"
      >
        <StyledContainer maxWidth="lg">{children}</StyledContainer>
      </Flex>
    </>
  );
}
