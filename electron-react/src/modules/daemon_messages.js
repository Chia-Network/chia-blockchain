export const daemonMessage = () => ({
  type: "OUTGOING_MESSAGE",
  message: {
    destination: "daemon"
  }
});

export const registerService = () => {
  var action = daemonMessage();
  action.message.command = "register_service";
  action.message.data = { service: "wallet_ui" };
  return action;
};

export const startService = service_name => {
  var action = daemonMessage();
  action.message.command = "start_service";
  action.message.data = { service: service_name };
  return action;
};

export const startServiceTest = service_name => {
  var action = daemonMessage();
  action.message.command = "start_service";
  action.message.data = { service: service_name, testing: true };
  return action;
};

export const stopService = service_name => {
  var action = daemonMessage();
  action.message.command = "stop_service";
  action.message.data = { service: service_name };
  return action;
};

export const isServiceRunning = service_name => {
  var action = daemonMessage();
  action.message.command = "is_running";
  action.message.data = { service: service_name };
  return action;
};
