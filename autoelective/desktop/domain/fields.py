from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    help: str
    default: Any
    type: type
    level: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None


CLIENT_FIELDS = (
    FieldSpec('supply_cancel_page', '旧版选课计划页码',
              '仅用于导入未设置单课页码的旧版配置。', 1, int, 'compatibility', 1, 999),
    FieldSpec('refresh_interval', '全局查询间隔',
              '页面级共享的标准查询间隔，默认 6 秒，长时间运行最短不得少于 4 秒。任何间隔都不能保证不被限流。', 6.0, float, 'strategy', 3, 3600),
    FieldSpec('random_deviation', '随机偏移',
              '查询间隔 ×（1 ± 偏移）。默认 0.2；设为 0 时使用固定间隔。', 0.2, float, 'strategy', 0, 0.9),
    FieldSpec('iaaa_client_timeout', '登录请求超时', '等待统一认证服务响应的最长秒数。',
              30.0, float, 'advanced', 1, 600),
    FieldSpec('elective_client_timeout', '选课请求超时',
              '等待选课服务响应的最长秒数。', 60.0, float, 'advanced', 1, 600),
    FieldSpec('elective_client_pool_size', '全局会话上限',
              '默认 4 个，最多 5 个。程序自动分配并轮换全部会话，主修与辅修共享上限；增加会话不会加快全局查询频率。', 4, int, 'advanced', 1, 5),
    FieldSpec('page_pool_size', '旧版每页会话额度',
              '仅兼容旧版配置；桌面调度器自动分配，不使用此值。', 1, int, 'compatibility', 1, 5),
    FieldSpec('elective_client_max_life', '会话有效期',
              '会话刷新前的最长秒数；-1 表示不限制。', 600, int, 'advanced', -1, 86400),
    FieldSpec('login_loop_interval', '登录重试间隔', '登录线程每轮结束后等待的秒数。',
              2.0, float, 'advanced', 0.1, 600),
    FieldSpec('print_mutex_rules', '记录互斥规则',
              '桌面模式固定记录互斥规则，无需配置。', True, bool, 'compatibility'),
    FieldSpec('debug_print_request', '请求调试日志',
              '记录请求细节，桌面模式会过滤认证信息。仅排查问题时启用。', False, bool, 'advanced'),
    FieldSpec('debug_dump_request', '保存请求诊断',
              '保存请求响应用于排查问题；诊断文件可能包含个人选课信息。', False, bool, 'advanced'),
)
