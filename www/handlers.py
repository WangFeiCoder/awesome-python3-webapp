# -*- coding: utf-8 -*-

import hashlib
import json
import logging
import re
import time

from aiohttp import web

import markdown2
from apis import APIError, APIValueError, APIPermissionError, Page, APIResourceNotFoundError
from coroweb import get, post
from config import configs
from models import User, Blog, Comment, next_id

logging.basicConfig(level=logging.INFO)
COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret


def check_admin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()


def get_page_index(page_str):
    p = 1
    try:
        p = int(page_str)
    except ValueError as e:
        pass
    if p < 1:
        p = 1
    return p


def text2html(text):
    '''将文本拼接成html格式文件'''
    lines = map(lambda s: '<p>%s</p>' % s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
                filter(lambda s: s.strip() != '', text.split('\n')))
    return ''.join(lines)


def user2cookie(user, max_age):
    """加密cookie"""
    expires = str(int(time.time() + max_age))  # 计算过期时间，以字符串返回
    s = '%s-%s-%s-%s' % (user.id, user.passwd, expires, _COOKIE_KEY)
    L = [user.id, expires, hashlib.sha1(s.encode('utf-8')).hexdigest()]
    return '-'.join(L)


async def cookie2user(cookie_str):
    '''解密cookie'''
    if not cookie_str:
        return None
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        uid, expires, sha1 = L
        if int(expires) < time.time():
            # cookie过期
            return None
        user = await User.find(uid)
        if user is None:
            return None
        s = '%s-%s-%s-%s' % (uid, user.passwd, expires, _COOKIE_KEY)
        if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():
            logging.info('invalid sha1')
            return None
        user.passwd = '******'
        return user
    except Exception as e:
        logging.exception(e)
        return None


# 用户浏览页面

@get('/')
async def blogs(*, page='1'):
    '''Blog首页'''
    page_index = get_page_index(page)
    num = await Blog.findNumber('count(id)')
    page = Page(num)
    if num == 0:
        blogs = []
    else:
        blogs = await Blog.findAll(orderBy='created_at desc', limit=(page.offset, page.limit))
    return {
        '__template__': 'blogs.html',
        'page': page,
        'blogs': blogs
    }


@get('/register')
def registerPage():
    '''返回用户注册页面'''
    return {
        '__template__': 'register.html'
    }


@get('/signin')
def signinPage():
    '''返回用户登录页面'''
    return {
        '__template__': 'signin.html'
    }


@get('/signout')
def signout(request):
    '''用户退出，将SESSION中的用户信息设置为无效，返回当前页面或首页'''
    referer = request.headers.get('Referer')  # 获取当前URL
    resp = web.HTTPFound(referer or '/')
    resp.set_cookie(COOKIE_NAME, '-signout-', max_age=0, httponly=True)
    # 也可以直接清除
    # resp.del_cookie(COOKIE_NAME)
    logging.info('user: %s signout.' % request.__user__.name)
    return resp


@get('/blog/{blog_id}')
async def viewBlog(*, blog_id):
    '''查阅一篇日志'''
    blog = await Blog.find(blog_id)
    comments = await Comment.findAll('blog_id=?', [blog_id], orderBy='created_at desc')
    for comment in comments:
        comment.html_content = text2html(comment.content)
    blog.html_content = markdown2.markdown(blog.content)
    return {
        '__template__': 'blog.html',
        'blog': blog,
        'comments': comments
    }


# 管理页面

@get('/manage/blogs')
def manageBlogs(*, page='1'):
    '''返回日志管理页'''
    return {
        '__template__': 'manage_blogs.html',
        'page_index': get_page_index(page)
    }


@get('/manage/blogs/create')
def manageCreateBlog():
    '''返回日志创建页'''
    return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs'
    }


@get('/manage/blogs/edit')
def manageEditBlog(*, id):
    return {
        '__template__': 'manage_blog_edit.html',
        'id': id,
        'action': '/api/blogs/%s' % id
    }


@get('/manage/users')
def manageUsers(*, page='1'):
    '''返回用户管理页'''
    return {
        '__template__': 'manage_users.html',
        'page_index': get_page_index(page)
    }


@get('/manage/comments')
def manageComments(*, page='1'):
    '''返回评论管理页'''
    return {
        '__template__': 'manage_comments.html',
        'page_index': get_page_index(page)
    }


# 后端API

@get('/api/blogs')
async def apiGetBlogs(*, page='1'):
    page_index = get_page_index(page)
    num = await Blog.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, blogs=())
    blogs = await Blog.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, blogs=blogs)


@post('/api/blogs')
async def apiCreateBlog(request, *, name, summary, content):
    check_admin(request)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty')
    blog = Blog(user_id=request.__user__.id, user_name=request.__user__.name, user_image=request.__user__.image,
                name=name.strip(), summary=summary.strip(), content=content.strip())
    await blog.save()
    return blog


@get('/api/blogs/{id}')
async def apiGetBlog(*, id):
    blog = await Blog.find(id)
    return blog


@post('/api/blogs/{blog_id}')
async def apiAmendBlog(blog_id, request, *, name, summary, content):
    check_admin(request)
    blog = await Blog.find(blog_id)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty')
    blog.name = name.strip()
    blog.summary = summary.strip()
    blog.content = content.strip()
    await blog.update()
    return blog


@post('/api/blogs/{blog_id}/delete')
async def apiDeleteBlog(request, *, blog_id):
    check_admin(request)
    blog = await Blog.find(blog_id)
    await blog.remove()
    return dict(id=blog_id)


@get('/api/comments')
async def apiGetComments(*, page='1'):
    page_index = get_page_index(page)
    num = await Comment.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, comments=())
    comments = await Comment.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, comments=comments)


@post('/api/blogs/{blog_id}/comments')
async def apiCreateComment(blog_id, request, *, content):
    user = request.__user__
    if user is None:
        raise APIPermissionError('please signin first.')
    if not content or not content.strip():
        raise APIValueError('content')
    blog = await Blog.find(blog_id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    comment = Comment(blog_id=blog.id, user_id=user.id, user_name=user.name, user_image=user.image,
                      content=content.strip())
    await comment.save()
    return comment


@post('/api/comments/{comment_id}/delete')
async def apiDeleteComment(comment_id, request):
    check_admin(request)
    comment = await Comment.find(comment_id)
    if comment is None:
        raise APIResourceNotFoundError('Comment')
    await comment.remove()
    return dict(id=comment_id)


@get('/api/users')
async def apiGetUsers(*, page='1'):
    page_index = get_page_index(page)
    num = await User.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, users=())
    users = await User.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    for u in users:
        u.passwd = '******'
    return dict(page=p, users=users)


_reEmail = re.compile(r'^[0-9a-z\.\-\_]+\@[0-9a-z\-\_]+(\.[0-9a-z\-\_]+){1,4}$')
_reSha1 = re.compile(r'^[0-9a-f]{40}$')  # SHA1不够安全，后续需升级


@post('/api/users')
async def apiCreateUser(*, name, email, passwd):
    '''用户注册'''
    # 输入验证
    if name is None or not name.strip():
        raise APIValueError('name', 'invalid name')
    if email is None or not _reEmail.match(email):
        raise APIValueError('email', 'invalid email')
    if passwd is None or not _reSha1.match(passwd):
        raise APIValueError('passwd', 'invalid password')
    users = await User.findAll('email=?', [email])
    if len(users) > 0:
        raise APIError('register failed', 'email', 'Email is already in use')
    # password 加密
    uid = next_id()
    sha1Passwd = '%s:%s' % (uid, passwd)
    u = User(id=uid, email=email, passwd=hashlib.sha1(sha1Passwd.encode('utf-8')).hexdigest(), name=name,
             image='http://www.gravatar.com/avatar/%s?s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
    await u.save()
    # session
    resp = web.Response()
    resp.set_cookie(COOKIE_NAME, user2cookie(u, 86400), max_age=86400, httponly=True)
    u.passwd = '******'
    resp.content_type = 'application/json'
    resp.body = json.dumps(u, ensure_ascii=False).encode('utf-8')
    return resp


@post('/api/authenticate')
async def apiAuthenticate(*, email, passwd):
    '''用户登录验证'''
    # 输入验证
    if not email:
        raise APIValueError('email', 'invalid email')
    if not passwd:
        raise APIValueError('passwd', 'invalid password')
    users = await User.findAll('email=?', [email])
    if len(users) == 0:
        raise APIValueError('email', 'email is not existed')
    # password验证
    u = users[0]
    sha1Passwd = '%s:%s' % (u.id, passwd)
    if u.passwd != hashlib.sha1(sha1Passwd.encode('utf-8')).hexdigest():
        raise APIValueError('passwd', 'password is wrong')
    # session
    resp = web.Response()
    resp.set_cookie(COOKIE_NAME, user2cookie(u, 86400), max_age=86400, httponly=True)
    u.passwd = '******'
    resp.content_type = 'application/json'
    resp.body = json.dumps(u, ensure_ascii=False).encode('utf-8')
    return resp
