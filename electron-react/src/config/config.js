module.exports = {
  local_test: process.env.NODE_ENV === 'development' && process.env.TESTNET !== 'true',
  backup_host: 'https://backup.chia.net',
};
