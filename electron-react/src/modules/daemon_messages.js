export const daemonMessage = () => ({
  type: "OUTGOING_MESSAGE",
  destination: "daemon"
});

export const registerService = () => {
  var action = daemonMessage();
  action.command = "register_service";
  action.data = { service: "wallet_ui" };
  return action;
};

export const startService = service_name => {
  var action = daemonMessage();
  action.command = "start_service";
  action.data = { service: service_name };
  return action;
};

export const stopService = service_name => {
  var action = daemonMessage();
  action.command = "stop_service";
  action.data = { service: service_name };
  return action;
};

export const isServiceRunning = service_name => {
  var action = daemonMessage();
  action.command = "is_running";
  action.data = { service: service_name };
  return action;
};
