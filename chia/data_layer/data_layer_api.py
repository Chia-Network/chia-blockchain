from chia.data_layer.data_layer import DataLayer


class DataLayerAPI:
    data_layer: DataLayer

    def __init__(self, data_layer) -> None:
        self.data_layer = data_layer

    # def _set_state_changed_callback(self, callback: Callable):
    #     self.full_node.state_changed_callback = callback

    @property
    def server(self):
        return self.data_layer.server

    @property
    def log(self):
        return self.data_layer.log

    @property
    def api_ready(self):
        return self.data_layer.initialized
