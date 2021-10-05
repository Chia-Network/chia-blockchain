export default {
  multipleWallets: process.env.MULTIPLE_WALLETS === 'true',
  local_test: process.env.LOCAL_TEST === 'true',
  asteroid: process.env.ASTEROID === 'true',
  backup_host: 'https://backup.chia.net',
};
