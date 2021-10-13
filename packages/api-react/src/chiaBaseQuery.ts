import { BaseQueryFn } from '@reduxjs/toolkit/query/react';
import { Client, ServiceName } from '@chia/api';

export const chiaBaseQuery = (
  options: { 
    client: Client,
  }
): BaseQueryFn<
  { 
    service: ServiceName;
    command: string; 
    variables?: any[],
  },
  unknown,
  Pick<ClientError, "name" | "message" | "stack">,
  Partial<Pick<ClientError, "request" | "response">>
> => {
  const { client } = options;

  return async (service, command, args) => {
    return client.service[command](command, ...args);
  };
};