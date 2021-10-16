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
    service?: Service;
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
    service: DefaultService,
  } = options;

  const services = new Map<Service, Service>();

  async function getServiceInstance(api: BaseQueryApi, ServiceClass: Service): Promise<Service> {
    if (!services.has(ServiceClass)) {
      const client = await getClientInstance(api);
      const serviceInstance = new ServiceClass(client);
      services.set(ServiceClass, serviceInstance);
    }
    
    return services.get(ServiceClass);
  }

  return async ({ command, service: ServiceClass = DefaultService, args = [] }, api) => {
    const serviceInstance = await getServiceInstance(api, ServiceClass);

    const meta = { 
      timestamp: Date.now(),
      command,
      args,
    };

    try {
      return { 
        data: await serviceInstance[command](...args),
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
