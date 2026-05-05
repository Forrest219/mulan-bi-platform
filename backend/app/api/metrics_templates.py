"""Metrics Template — FastAPI 路由层（Jinja2 渲染预览）"""

from fastapi import APIRouter, Body, status

from services.metrics_agent.template_renderer import TemplateRenderer

router = APIRouter()


@router.post(
    "/render-template",
    summary="渲染 formula_template",
    status_code=status.HTTP_200_OK,
)
def render_template(
    template: str = Body(..., description="Jinja2 模板字符串"),
    context: dict = Body(..., description="渲染变量上下文"),
):
    """
    在沙箱中渲染 formula_template，返回渲染后的 SQL 片段。

    用于指标详情页的公式模板预览功能。
    模板渲染使用 jinja2.sandbox.SandboxedEnvironment，禁止危险属性访问。
    """
    renderer = TemplateRenderer()
    try:
        result = renderer.render(template, context)
        return {"success": True, "result": result}
    except ValueError as e:
        return {"success": False, "error": str(e)}