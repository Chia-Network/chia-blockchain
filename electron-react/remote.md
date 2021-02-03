# Connecting the UI to a Remote Daemon

To connect the electron UI to a daemon running somewhere other than `localhost` ensure the following:

- Ensure your `config.yaml` file has a `ui` section that includes these settings:

````yaml
ui:
  daemon_host: farmer # the host name or IP where the daemon is running
  daemon_port: 55400
  ssl:
    crt: trusted.crt
    key: trusted.key
````

- The build will set this, but if running from source, ensure that `package.json` has a [version property](https://docs.npmjs.com/cli/v6/configuring-npm/package-json#version)
  - The electron package versions differ from how the python code sets versions but this is needed for the UI code to find the correct `config.yaml`
  - _example:_ `"version": "0.1.23"` will point to the config folder at `~/.chia/beta-1.0b23/`

- The remote daemon must be reachable at `wss://<daemon_host>:<daemon_port>`
- The certs must be shared by the UI and the remote daemon
