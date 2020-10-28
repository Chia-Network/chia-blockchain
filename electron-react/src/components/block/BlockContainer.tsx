import React, { ReactNode } from 'react';
import { Card, CardContent } from '@material-ui/core';

type Props = {
  children: ReactNode,
};

export default function BlockContainer(props: Props): JSX.Element {
  const { children } = props;

  return (
    <Card>
      <CardContent>
        <div>
          {children}
        </div>
      </CardContent>
    </Card>
  );
}
