class DemoAPI:
    def __init__(self, v):
        self._v = v

    async def add(self, t: int) -> int:
        return self._v + t

    async def multiply(self, t: int) -> int:
        return self._v * t

    async def inc(self) -> None:
        self._v += 1


'''
You can run this demo from the command-line, using ipython

pip install ipython

SERVER:

ipython

import asyncio; from src.remote.demo import DemoAPI; from src.remote.websocket_server import simple_server; d = DemoAPI(100); await asyncio.Task(simple_server(12345, d))


CLIENT:

ipython
from src.remote.demo import DemoAPI; from src.remote.websocket_client import connect_to_remote_api; demo = await connect_to_remote_api("ws://127.0.0.1:12345/ws/", DemoAPI)
print(await demo.add(100))
print(await demo.inc())



TO LOG THE JSON, apply this patch:

--- a/src/remote/JSONMessage.py
+++ b/src/remote/JSONMessage.py
@@ -14,6 +14,7 @@ class JSONMessage:
 
     @classmethod
     def deserialize_text(cls, text):
+        print(text)
         return cls(json.loads(text))
 
     def serialize(self):
'''
