from aiohttp import web
import jinja2
import aiohttp_jinja2
import os
from src.util.config import load_config_cli
from middlewares import setup_middlewares
from node_state import init_rpc


# setup the directoriers (relative to this file) and app object
abs_app_dir_path = os.path.dirname(os.path.realpath(__file__))
abs_template_path = os.path.join(abs_app_dir_path, 'views')
abs_static_path = os.path.join(abs_app_dir_path, 'static')

app = web.Application()
app['config'] = load_config_cli("config.yaml", "ui")
env = aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(abs_template_path))
app['static_root_url'] = 'static'
routes = web.RouteTableDef()
app.router.add_static('/static/', path=abs_static_path, name='static')
setup_middlewares(app)
app.on_startup.append(init_rpc)


@routes.get('/')
@aiohttp_jinja2.template('index.jinja2')
async def index(request):
    # the node property contains the state of the chia node when it was last queried
    return app['node']


app.add_routes(routes)
web.run_app(app, port=app['config']['webui_port'])
