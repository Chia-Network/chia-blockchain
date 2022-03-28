import React, { ReactNode } from 'react';
import { Flex } from '@chia/core';
import { ArrowBackIos as ArrowBackIosIcon } from '@mui/icons-material';
import { useNavigate, useParams } from 'react-router-dom';
import styled from 'styled-components';

const BackIcon = styled(ArrowBackIosIcon)`
  font-size: 1.25rem;
  cursor: pointer;
`;

type Props = {
  children?: ReactNode;
};

export default function BlockTitle(props: Props) {
  const { children } = props;
  const navigate = useNavigate();

  function handleGoBack() {
    navigate('/dashboard');
  }

  return (
    <Flex gap={1} alignItems="baseline">
      <BackIcon onClick={handleGoBack}> </BackIcon>
      <span>{children}</span>
    </Flex>
  );
}

BlockTitle.defaultProps = {
  children: undefined,
};
