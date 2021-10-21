type Invalidate = {
  command: string;
  endpoint: () => Object;
  canInvalidate?: (data: any, args: any) => boolean;
};

export default function onCacheEntryAddedInvalidate(rtkQuery, invalidates: Invalidate[]) {
  return async (args, api) => {
    const { cacheDataLoaded, cacheEntryRemoved, dispatch } = api;
    const unsubscribes: Function[] = [];
    try {
      await cacheDataLoaded;

      await Promise.all(invalidates.map(async(invalidate) => {
        const { command, endpoint, canInvalidate } = invalidate;

        const currentEndpoint = endpoint();

        const response = await rtkQuery({
          command: command,
          args: [(data) => {
            if (canInvalidate && !canInvalidate(data, args)) {
              return;
            }
            dispatch(currentEndpoint.initiate(args, { 
              subscribe: false,
              forceRefetch: true,
            }));
          }],
        }, api, {});

        if (response.data) {
          unsubscribes.push(response.data);
        }
      }));
    } finally {
      await cacheEntryRemoved;
      unsubscribes.forEach((unsubscribe) => unsubscribe());
    }
  }
}
