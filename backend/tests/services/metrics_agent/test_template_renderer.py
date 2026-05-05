"""测试 Metrics Agent Jinja2 沙箱渲染器"""

import pytest

from services.metrics_agent.template_renderer import TemplateRenderer


class TestTemplateRendererSandboxEscape:
    """防止沙箱逃逸攻击测试"""

    def test_blocks_mro_subclasses(self):
        """禁止 {{ ''.__class__.__mro__[1].__subclasses__() }} 等沙箱逃逸"""
        renderer = TemplateRenderer()
        with pytest.raises(ValueError, match="模板渲染失败"):
            renderer.render("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})

    def test_blocks_init_globals(self):
        """禁止 {{ ''.__class__.__init__.__globals__ }} 等属性访问"""
        renderer = TemplateRenderer()
        with pytest.raises(ValueError, match="模板渲染失败"):
            renderer.render("{{ ''.__class__.__init__.__globals__ }}", {})

    def test_blocks_read_private_attributes(self):
        """禁止 {{ obj.__private__ }} 读操作"""
        renderer = TemplateRenderer()
        with pytest.raises(ValueError, match="模板渲染失败"):
            renderer.render("{{ ''.__class__.__dict__ }}", {})

    def test_blocks_setattr(self):
        """禁止 {{ obj.__setattr__ }} 写操作"""
        renderer = TemplateRenderer()
        with pytest.raises(ValueError, match="模板渲染失败"):
            renderer.render("{{ config.__class__.__setattr__ }}", {})

    def test_blocks_import(self):
        """禁止 import 语句"""
        renderer = TemplateRenderer()
        with pytest.raises(ValueError, match="模板渲染失败"):
            renderer.render("{% import os %}", {})


class TestTemplateRendererAllowedFilters:
    """允许的过滤器测试"""

    def test_tojson_filter(self):
        """允许 tojson 过滤器"""
        renderer = TemplateRenderer()
        result = renderer.render('{{ value | tojson }}', {"value": {"a": 1}})
        assert '"a"' in result

    def test_string_filter(self):
        """允许 string 过滤器"""
        renderer = TemplateRenderer()
        result = renderer.render('{{ value | string }}', {"value": 42})
        assert "42" in result

    def test_int_filter(self):
        """允许 int 过滤器"""
        renderer = TemplateRenderer()
        result = renderer.render('{{ value | int }}', {"value": "123"})
        assert "123" in result

    def test_float_filter(self):
        """允许 float 过滤器"""
        renderer = TemplateRenderer()
        result = renderer.render('{{ value | float }}', {"value": "3.14"})
        assert "3.14" in result


class TestTemplateRendererNormalUsage:
    """正常渲染场景测试"""

    def test_simple_variable_substitution(self):
        """简单变量替换"""
        renderer = TemplateRenderer()
        result = renderer.render("SELECT {{ col }} FROM {{ table }}", {"col": "id", "table": "users"})
        assert result == "SELECT id FROM users"

    def test_multiple_variables(self):
        """多变量替换"""
        renderer = TemplateRenderer()
        result = renderer.render(
            "WHERE tenant_id = {{ tenant_id }} AND status = '{{ status }}'",
            {"tenant_id": 42, "status": "active"},
        )
        assert "42" in result
        assert "active" in result

    def test_filter_usage(self):
        """过滤器组合使用"""
        renderer = TemplateRenderer()
        result = renderer.render(
            '{"id": {{ user_id | int }}, "name": "{{ name | string }}"}',
            {"user_id": "100", "name": "Alice"},
        )
        assert "100" in result
        assert "Alice" in result


class TestTemplateRendererEdgeCases:
    """边界情况测试"""

    def test_empty_context(self):
        """无变量时模板正常渲染（不含变量）"""
        renderer = TemplateRenderer()
        result = renderer.render("SELECT 1 AS dummy", {})
        assert result == "SELECT 1 AS dummy"

    def test_missing_variable_raises(self):
        """缺失变量应抛出错误"""
        renderer = TemplateRenderer()
        with pytest.raises(ValueError, match="模板渲染失败"):
            renderer.render("SELECT {{ missing_var }}", {})

    def test_invalid_template_syntax(self):
        """模板语法错误应抛出 ValueError"""
        renderer = TemplateRenderer()
        with pytest.raises(ValueError, match="模板渲染失败"):
            renderer.render("{{ {{{{", {})