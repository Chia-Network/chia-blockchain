const net = require("net");
const port = process.env.PORT ? process.env.PORT - 100 : 3000;
const config = require("./util/config");

process.env.ELECTRON_START_URL = `http://${config.self_hostname}:${port}`;

const client = new net.Socket();

let startedElectron = false;
const tryConnection = () =>
  client.connect({ port: port }, () => {
    client.end();
    if (!startedElectron) {
      console.log("starting electron");
      startedElectron = true;
      const exec = require("child_process").exec;
      const electron = exec("npm run electron");
      electron.stdout.on("data", function(data) {
        console.log("stdout: " + data.toString());
      });
    }
  });

tryConnection();

client.on("error", error => {
  setTimeout(tryConnection, 1000);
});
