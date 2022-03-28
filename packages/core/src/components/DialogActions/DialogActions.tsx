import styled from 'styled-components';
import { DialogActions } from '@mui/material';

export default styled(DialogActions)`
  padding: ${({ theme }) => `${theme.spacing(2)} ${theme.spacing(3)}`};
`;
