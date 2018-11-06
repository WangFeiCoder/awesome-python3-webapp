# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import os
import time
from datetime import datetime

from aiohttp import web
from jinja2 import Environment, FileSystemLoader

import config
import orm
from coroweb import add_routes, add_static
from handlers import cookie2user, COOKIE_NAME

logging.basicConfig(level=logging.INFO)


async def logger_factory(app, handler):
    ' 中间件，相当于一堵墙，可以在处理请求前，对请求进行验证、筛选、记录等操作 '

    async def logger(request):
        ' 记录日志 '
        logging.info('Request: %s %s' % (request.method, request.path))
        ' 继续处理请求 '
        return (await handler(request))

    return logger


async def response_factory(app, handler):
    async def response(request):
        logging.info('Response handler')
        ' 对处理函数的响应进行处理 '
        r = await handler(request)
        if isinstance(r, web.StreamResponse):
            # 处理响应流
            return r
        if isinstance(r, bytes):
            # 处理字节类响应
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        if isinstance(r, str):
            # 处理字符串类响应
            if r.startswith('redirect:'):
                # 返回重定向响应
                return web.HTTPFound(r[9:])
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp  # 返回HTML
        if isinstance(r, dict):
            # 处理字典类响应
            r['__user__'] = request.__user__
            template = r.get('__template__')
            if template is None:
                # 返回JSON类响应
                resp = web.Response(
                    body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            else:
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                # 获取模板，并传入响应参数进行渲染，生成HTML
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        if isinstance(r, int) and r >= 100 and r < 600:
            # 处理响应码
            return web.Response(r)
        if isinstance(r, tuple) and len(r) == 2:
            # 处理有描述信息的响应码
            t, m = r
            if isinstance(t, int) and t >= 100 and t < 600:
                return web.Response(t, str(m))
        # 其他响应的返回
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp

    return response


async def auth_factory(app, handler):
    async def auth(request):
        '''分析COOKIE，就登录用户绑定到requet对象'''
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = await cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
            if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
                return web.HTTPFound('/signin')
        return (await handler(request))

    return auth


def init_jinja2(app, **kw):
    '''模板引擎初始化'''
    logging.info('init jinja2')
    options = dict(
        autoescape=kw.get('autoescape', True),  # 默认打开自动转义 转义字符
        block_start_string=kw.get('block_start_string', '{%'),  # 模板控制块的字符串 {% block %}
        block_end_string=kw.get('block_end_string', '%}'),
        variable_start_string=kw.get('variable_start_string', '{{'),  # 模板变量的字符串 {{ var/func }}
        variable_end_string=kw.get('variable_end_string', '}}'),
        auto_reload=kw.get('auto_reload', True)
    )
    path = kw.get('path', None)
    if path is None:
        # 获得模板路径
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    env = Environment(loader=FileSystemLoader(path), **options)  # 用文件系统加载器加载模板
    filters = kw.get('filters', None)  # 尝试获取过滤器
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f
    app['__templating__'] = env  # 给Web实例程序绑定模板属性


def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1 minute ago'
    if delta < 3600:
        return u'%s minutes ago' % (delta // 60)
    if delta < 86400:
        return u'%s hours ago' % (delta // 3600)
    if delta < 604800:
        return u'%s day ago' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s-%s-%s' % (dt.year, dt.month, dt.day)


async def init(loop):
    ' 服务器运行程序：创建web实例程序，该实例程序绑定路由和处理函数，运行服务器，监听端口请求，送到路由处理 '
    await orm.create_pool(loop=loop, **config.configs.db)
    app = web.Application(loop=loop, middlewares=[logger_factory, auth_factory, response_factory])
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    add_routes(app, 'handlers')
    add_static(app)
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('Server started at http://127.0.0.1:9000')
    return srv


loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()
