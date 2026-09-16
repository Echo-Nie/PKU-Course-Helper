#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: hook.py
# modified: 2019-09-11

import os
import re
import time
from urllib.parse import quote, urlparse
from .logger import ConsoleLogger
from .config import AutoElectiveConfig
from .parser import get_tree_from_response, get_title, get_errInfo, get_tips
from .utils import pickle_gzip_dump
from .const import REQUEST_LOG_DIR
from .exceptions import *
from .school_feedback import system_exception, tips_exception
from ._internal import mkdir

cout = ConsoleLogger("hook")
config = AutoElectiveConfig()

_USER_REQUEST_LOG_DIR = os.path.join(REQUEST_LOG_DIR, config.get_user_subpath())
mkdir(_USER_REQUEST_LOG_DIR)

_DUMMY_HOOK = {"response": []}


def get_hooks(*fn):
    return {"response": fn}

def merge_hooks(*hooklike):
    funcs = []
    for hook in hooklike:
        if isinstance(hook, dict):
            funcs.extend(hook["response"])
        elif callable(hook): # function
            funcs.append(hook)
        else:
            raise TypeError(hook)
    return get_hooks(*funcs)

def with_etree(r, **kwargs):
    r._tree = get_tree_from_response(r)

def del_etree(r, **kwargs):
    del r._tree


def check_status_code(r, **kwargs):
    if os.environ.get("PKU_AUTOELECTIVE_DATA_DIR") and r.status_code in (403, 429):
        error = AccessLimitedError("学校系统已限制访问")
        error.response = r
        raise error
    if r.status_code != 200:
        if r.status_code in (301,302,304):
            pass
        elif r.status_code in (500,501,502,503):
            raise ServerError(response=r)
        else:
            raise StatusCodeError(response=r)


def check_iaaa_success(r, **kwargs):
    respJson = r.json()
    if not isinstance(respJson, dict):
        raise IAAANotSuccessError(response=r, msg='认证响应格式异常，请稍后重试')

    if not respJson.get("success", False):
        try:
            errors = respJson["errors"]
            code = errors["code"]
            msg = errors["msg"]
        except Exception as e:
            cout.error(e)
            cout.info("Unable to get errcode/errmsg from response JSON")
            pass
        else:
            if code == "E01":
                raise IAAAIncorrectPasswordError(response=r, msg=msg)
            elif code == "E21":
                raise IAAAForbiddenError(response=r, msg=msg)

        raise IAAANotSuccessError(response=r)


def check_elective_title(r, **kwargs):
    assert hasattr(r, "_tree")

    title = get_title(r._tree)
    if title is None:
        return

    try:
        if title.strip() in ("系统异常", "系统提示"):
            try:
                err = get_errInfo(r._tree)
            except (ValueError, IndexError, AttributeError, AssertionError):
                err = '学校返回系统异常页，但提示区域结构无法识别；未记录整页正文'
            raise system_exception(err)(response=r, msg=err)

    except Exception as e:
        if "_client" in r.request.__dict__:  # _client will be set by BaseClient
            r.request._client.persist_cookies(r)
        raise e


def check_elective_tips(r, **kwargs):
    assert hasattr(r, "_tree")
    if r._tree is None:
        raise UnexpectedHTMLFormat(response=r, msg='学校返回空页面，请稍后重试')
    tips = get_tips(r._tree)

    try:

        if tips is None:
            return

        kind = tips_exception(tips)
        if kind is TipsException and not os.environ.get('PKU_AUTOELECTIVE_DATA_DIR'):
            cout.warning("Unknown tips: %s" % tips)
            return
        # Desktop stdout is private IPC: console warnings are otherwise lost.
        raise kind(response=r, msg=tips)

    except Exception as e:
        if "_client" in r.request.__dict__:  # _client will be set by BaseClient
            r.request._client.persist_cookies(r)
        raise e


def debug_print_request(r, **kwargs):
    if not config.is_debug_print_request:
        return
    cout.debug("> %s  %s" % (r.request.method, r.url))
    cout.debug("> Headers:")
    for k, v in r.request.headers.items():
        cout.debug("%s: %s" % (k, v))
    cout.debug("> Body:")
    cout.debug(r.request.body)
    cout.debug("> Response Headers:")
    for k, v in r.headers.items():
        cout.debug("%s: %s" % (k, v))
    cout.debug("")


def _dump_request(r):
    if os.environ.get("PKU_AUTOELECTIVE_DATA_DIR"):
        return "disabled in desktop mode"
    if "_client" in r.request.__dict__:  # _client will be set by BaseClient
        client = r.request._client
        r.request._client = None  # don't save client object

    hooks = r.request.hooks
    r.request.hooks = _DUMMY_HOOK  # don't save hooks array

    timestamp = time.strftime("%Y-%m-%d_%H.%M.%S%z")
    basename = quote(urlparse(r.url).path, '')
    filename = "%s.%s.gz" % (timestamp, basename)  # put timestamp first
    file = os.path.normpath(os.path.abspath(os.path.join(_USER_REQUEST_LOG_DIR, filename)))

    pickle_gzip_dump(r, file)

    # restore objects defined by autoelective package
    if "_client" in r.request.__dict__:
        r.request._client = client
    r.request.hooks = hooks

    return file


def debug_dump_request(r, **kwargs):
    if not config.is_debug_dump_request:
        return
    file = _dump_request(r)
    cout.debug("Dump request %s to %s" % (r.url, file))
