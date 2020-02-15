from aiohttp import web
import jinja2
import aiohttp_jinja2
import os
from src.rpc.rpc_client import RpcClient

# setup the views directory (relative to this file) and app object
abs_app_dir_path = os.path.dirname(os.path.realpath(__file__))
abs_template_path = os.path.join(abs_app_dir_path, 'views')
app = web.Application()

env = aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(abs_template_path))
app['static_root_url'] = '/static'
routes = web.RouteTableDef()


@routes.get('/')
@aiohttp_jinja2.template('tmpl.jinja2')
async def index(request):
    rpc_client: RpcClient = await RpcClient.create(8555)
    connections = await rpc_client.get_connections()
    c = len(connections)
    rpc_client.close()
    return {'title': 'Chia Node', 'connections': c}


app.add_routes(routes)
web.run_app(app)
