"""Metrics Agent — Jinja2 沙箱渲染服务

Spec 30 §12 架构红线：formula_template Jinja2 渲染必须在沙箱环境执行，
禁止动态导入模块或执行任意代码。
"""

import jinja2
from jinja2.sandbox import SandboxedEnvironment, SecurityError
from jinja2 import StrictUndefined


class TemplateRenderer:
    """
    Jinja2 模板沙箱渲染器。

    - 使用 jinja2.sandbox.SandboxedEnvironment 防止属性访问等沙箱逃逸
    - 禁止 __class__, __mro__, __subclasses__, __init__.__globals__ 等危险属性
    - autoescape=False 以保证 SQL 片段拼接正常
    """

    __slots__ = ("_env",)

    def __init__(self) -> None:
        # Jinja2 3.1.6 的 SandboxedEnvironment 不支持 allowed_filters 参数
        # 沙箱通过禁止危险属性访问来防止沙箱逃逸
        # 使用 StrictUndefined 使缺失变量时立即报错而非静默渲染空字符串
        self._env = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined)

    def render(self, template_str: str, context: dict) -> str:
        """
        渲染 formula_template SQL 片段。

        Args:
            template_str: Jinja2 模板字符串（如 "SELECT {{ col }} FROM {{ table }}"）
            context: 渲染变量字典（如 {"col": "id", "table": "users"}）

        Returns:
            渲染后的 SQL 片段字符串

        Raises:
            ValueError: 模板语法错误或沙箱拒绝访问
        """
        try:
            template = self._env.from_string(template_str)
            return template.render(**context)
        except (jinja2.TemplateError, SecurityError) as e:
            raise ValueError(f"模板渲染失败: {e}")