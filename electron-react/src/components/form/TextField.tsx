import styled from 'styled-components';
import { TextField } from '@material-ui/core';

export default styled(TextField)`
  color: #ffffff;

  & .MuiFormLabel-root {
    color: #e3f2fd;
  }

  & .MuiInputLabel-root {
    color: #e3f2fd;
  }

  & label.Mui-focused {
    color: #e3f2fd;
  }

  & label.Mui-required {
    color: #e3f2fd;
  }

  & label.Mui-disabled {
    color: #e3f2fd;
  }

  & label.Mui-root {
    color: #e3f2fd;
  }

  & .MuiInput-underline:after {
    border-bottom-color: #e3f2fd;
  }

  & .MuiOutlinedInput-root {
    & fieldset {
      border-color: #e3f2fd;
    }
    &:hover fieldset {
      border-color: #e3f2fd;
    }
    &.Mui-focused fieldset {
      border-color: #e3f2fd;
    }
    &.Mui-disabled fieldset {
      border-color: #e3f2fd;
    }
  }

  & .MuiOutlinedInput-input {
    color: #ffffff;
  }
`;
