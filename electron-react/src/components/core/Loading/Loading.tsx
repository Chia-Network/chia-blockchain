import { CircularProgress } from '@material-ui/core';
import styled from 'styled-components';

export default styled(CircularProgress)`
  color: ${({ theme }) =>
    theme.palette.type === 'dark' ? 'white' : 'inherit'}; ;
`;
