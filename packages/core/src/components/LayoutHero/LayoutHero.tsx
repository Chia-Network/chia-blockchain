import React, { ReactNode } from 'react';
import { AppBar, Toolbar, Box } from '@material-ui/core';
import styled from 'styled-components';
import { Outlet, Link } from 'react-router-dom';
import { Flex } from '@chia/core';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import Settings from '../Settings';

const StyledWrapper = styled(Box)`
  padding-top: ${({ theme }) => `${theme.spacing(3)}px`};
  display: flex;
  flex-direction: column;
  flex-grow: 1;
  background: ${({ theme }) =>
    theme.palette.type === 'dark'
      ? `linear-gradient(45deg, #222222 30%, #333333 90%)`
      : `linear-gradient(45deg, #ffffff 30%, #fdfdfd 90%)`};
`;

const StyledBody = styled(Box)`
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  flex-grow: 1;
`;

type Props = {
  children?: ReactNode;
  header?: ReactNode;
  back?: boolean;
  outlet?: boolean;
  settings?: ReactNode;
};

export default function LayoutHero(props: Props) {
  const { children, header, back, outlet, settings } = props;

  return (
    <StyledWrapper>
      <AppBar color="transparent" elevation={0}>
        <Toolbar>
          {header}
          {back && (
            <Link to="-1">
              <ArrowBackIosIcon fontSize="large" color="secondary" />
            </Link>
          )}
          <Flex flexGrow={1} />
          <Settings>
            {settings}
          </Settings>
        </Toolbar>
      </AppBar>
      <StyledBody>
        <Flex flexDirection="column" gap={2} alignItems="center" alignSelf="stretch">
          {outlet ? <Outlet /> : children}
        </Flex>
      </StyledBody>
    </StyledWrapper>
  );
}

LayoutHero.defaultProps = {
  header: undefined,
  children: undefined,
  back: false,
  outlet: false,
};
