console.log('*DEV', process.env.NODE_ENV === 'development');

module.exports = {
  local_test: process.env.NODE_ENV === 'development',
  backup_host: 'https://backup.chia.net',
};
