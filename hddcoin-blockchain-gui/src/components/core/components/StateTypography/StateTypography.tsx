import React from 'react';
import styled from 'styled-components';
import { Typography } from '@material-ui/core';
import State from '../../constants/State';
import StateColor from '../../constants/StateColor';

const Color = {
  [State.SUCCESS]: StateColor.SUCCESS,
  [State.WARNING]: StateColor.WARNING,
  [State.ERROR]: StateColor.ERROR,
};

export default styled(({ state, ...rest }) => <Typography {...rest} />)`
  ${({ state }) => (state ? `color: ${Color[state]};` : '')}
`;
