import { createGlobalStyle } from 'styled-components';

import robotoMedium from './Roboto-Medium.ttf';
import robotoRegular from './Roboto-Regular.ttf';
import robotoLight from './Roboto-Light.ttf';

export default createGlobalStyle`
  @font-face {
    font-family: Roboto;
    src: url(${robotoMedium});
    font-weight: 500;
  }

  @font-face {
    font-family: Roboto;
    src: url(${robotoRegular});
    font-weight: 400;
  }

  @font-face {
    font-family: Roboto;
    src: url(${robotoLight});
    font-weight: 300;
  }
`;
