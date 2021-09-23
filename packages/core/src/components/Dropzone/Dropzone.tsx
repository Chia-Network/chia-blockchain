import React, { ReactNode } from 'react';
import { Paper, CircularProgress } from '@material-ui/core';
import styled from 'styled-components';
import { useDropzone, DropzoneOptions } from 'react-dropzone';
import AspectRatio from '../AspectRatio';
import Flex from '../Flex';

const StyledPaper = styled(Paper)`
  background-color: #999999;
  padding: ${({ theme }) => `${theme.spacing(1)}px ${theme.spacing(2)}px`};
`;

type ChildrenRender = (input: { isDragActive: boolean }) => ReactNode;

type Props = {
  children: ReactNode | ChildrenRender;
  onDrop: (acceptedFiles: File[]) => void;
  maxFiles?: number;
  accept?: string[]; // ['image/jpeg', 'image/png']
  ratio: number;
  processing?: boolean;
};

export default function Dropzone(props: Props) {
  const { children, onDrop, maxFiles, accept, ratio, processing } = props;

  const config: DropzoneOptions = {
    onDrop,
    maxFiles,
  };

  if (accept) {
    config.accept = accept.join(', ');
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone(config);
  const childrenContent =
    typeof children === 'function' ? children({ isDragActive }) : children;

  return (
    <div {...getRootProps()}>
      <input {...getInputProps()} />
      <StyledPaper>
        <AspectRatio ratio={ratio}>
          <Flex
            alignItems="center"
            justifyContent="center"
            flexDirection="column"
            height="100%"
          >
            {processing ? (
              <CircularProgress color="secondary" />
            ) : (
              childrenContent
            )}
          </Flex>
        </AspectRatio>
      </StyledPaper>
    </div>
  );
}

Dropzone.defaultProps = {
  maxFiles: undefined,
  accept: undefined,
  ratio: 16 / 6,
  processing: false,
};
