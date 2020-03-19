from aiohttp import web
import jinja2
import aiohttp_jinja2
import os
from src.util.config import load_config_cli
from middlewares import setup_middlewares
from node_state import query_node, find_block
from blspy import PrivateKey
import urllib.parse


def setup_app():
    app = web.Application()
    app['ready'] = False
    try:
        abs_app_dir_path = os.path.dirname(os.path.realpath(__file__))
        aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(os.path.join(abs_app_dir_path, 'views')))
        app.router.add_static('/static/', path=os.path.join(abs_app_dir_path, 'static'), name='static')
        setup_middlewares(app)

        app['config'] = load_config_cli("config.yaml", "ui")
        app['key_config'] = load_config_cli("keys.yaml", None)
        app['key_config']['pool_pks'] = [
                        PrivateKey.from_bytes(bytes.fromhex(ce)).get_public_key()
                        for ce in app['key_config']["pool_sks"]
                    ]

        app.on_startup.append(query_node)

    finally:
        return app


app = setup_app()
routes = web.RouteTableDef()


@routes.get('/')
@aiohttp_jinja2.template('index.jinja2')
async def index(request):
    # the node property contains the state of the chia node when it was last queried
    if app['ready']:
        return dict(title='Chia Full Node', **app['node'])

    return {}


@routes.get('/lca')
@aiohttp_jinja2.template('shb.jinja2')
async def lca(request):
    # the node property contains the state of the chia node when it was last queried
    if app['ready']:
        block = app['node']['blockchain_state']['lca']
        return dict(title='Least Common Ancestor', block=block)

    return {}


@routes.get('/tips/{blockid}')
@aiohttp_jinja2.template('shb.jinja2')
async def tips(request):
    # the node property contains the state of the chia node when it was last queried
    if app['ready']:
        blockid = urllib.parse.unquote(request.match_info['blockid'])
        state = app['node']['blockchain_state']
        block = find_block(state['tips'], blockid)
        if block != {}:
            return dict(title='Tip', block=block)

    raise web.HTTPNotFound()


app.add_routes(routes)
web.run_app(app, port=app['config']['webui_port'])
