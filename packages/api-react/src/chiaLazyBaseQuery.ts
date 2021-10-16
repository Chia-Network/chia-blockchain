import { BaseQueryFn } from '@reduxjs/toolkit/query/react';
import Client, { Service } from '@chia/api';
import { BaseQueryApi } from '@reduxjs/toolkit/dist/query/baseQueryTypes';
import { selectApiConfig } from './slices/api';

let clientInstance: Client;

async function getClientInstance(api: BaseQueryApi): Promise<Client> {
  if (!clientInstance) {
    const config = selectApiConfig(api.getState());
    if (!config) {
      throw new Error('Client API config is not defined. Dispatch initializeConfig first');
    }
    clientInstance = new Client(config);
  }

  return clientInstance;
}

type Options = {
  service: Service;
};

export default function chiaLazyBaseQuery(options: Options): BaseQueryFn<
  {
    command: string; 
    args?: any[],
  },
  unknown,
  unknown,
  {},
  {
    timestamp: number;
    command: string;
    args?: any[];
  }
> {
  const { 
    service: Service,
  } = options;

  let serviceInstance: Service;

  async function getServiceInstance(api: BaseQueryApi): Promise<Service> {
    if (!serviceInstance) {
      const client = await getClientInstance(api);
      serviceInstance = new Service(client);
    }
    
    return serviceInstance;
  }

  return async ({ command, args = [] }, api) => {
    const service = await getServiceInstance(api);

    const meta = { 
      timestamp: Date.now(),
      command,
      args,
    };

    try {
      return { 
        data: await service[command](...args),
        meta,
      };
    } catch(error) {
      return { 
        error,
        meta,
      };
    }
  };
}
