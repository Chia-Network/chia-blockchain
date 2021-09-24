import os from 'os';

const platform = os.platform();

export default platform && platform.startsWith('win');
