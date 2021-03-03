import styled from 'styled-components';
import { DialogActions } from '@material-ui/core';

export default styled(DialogActions)`
  padding: ${({ theme }) => `${theme.spacing(2)}px ${theme.spacing(3)}px`};
`;
