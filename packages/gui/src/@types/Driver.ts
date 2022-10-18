type Driver = {
  type: 'singleton';
  launcher_id: string;
  launcher_ph: string;
  also: {
    type: 'metadata';
    metadata: any;
    updater_hash: string;
    also?: {
      type: 'ownership';
      owner: '()';
      transfer_program: {
        type: 'royalty transfer program';
        launcher_id: string;
        royalty_address: string;
        royalty_percentage: string;
      };
    };
  };
};

export default Driver;
