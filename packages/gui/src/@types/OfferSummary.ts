type OfferSummary = {
  fees: number;
  offered: Record<string, number>;
  requested: Record<string, number>;
  infos: Record<
    string,
    | {
        tail: string;
        type: 'CAT';
      }
    | {
        launcherId: string;
        launcherPh: string;
        type: 'singleton';
        also: {
          type: 'metadata';
          metadata: string;
          updaterHash: string;
          also?: {
            type: 'ownership';
            owner: '()';
            transferProgram: {
              type: 'royalty transfer program';
              launcherId: string;
              royaltyAddress: string;
              royaltyPercentage: string;
            };
          };
        };
      }
  >;
};

export default OfferSummary;
