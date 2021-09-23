import React, { ReactNode } from 'react';
import Flex from '../Flex';
import { Typography } from '@material-ui/core';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useHistory } from 'react-router-dom';
import styled from 'styled-components';

const BackIcon = styled(ArrowBackIosIcon)`
  cursor: pointer;
`;

type Props = {
  children?: ReactNode;
  goBack?: boolean;
  to?: string;
  variant?: string;
  fontSize?: string;
};

export default function Back(props: Props) {
  const { children, variant, to, goBack, fontSize } = props;
  const history = useHistory();

  function handleGoBack() {
    if (goBack && history.length) {
      history.goBack();
      return;
    }
  
    if (to) {
      history.push(to);
    }
  }

  return (
    <Flex gap={1} alignItems="center">
      <BackIcon onClick={handleGoBack} fontSize={fontSize} />
      <Typography variant={variant}>{children}</Typography>
    </Flex>
  );
}

Back.defaultProps = {
  children: undefined,
  variant: "body2",
  goBack: true,
  to: undefined,
  fontSize: "medium",
};
