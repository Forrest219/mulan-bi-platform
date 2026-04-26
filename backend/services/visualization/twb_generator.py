"""
TWB 骨架生成器 — TWB Generator (Spec 26 附录 A §4.2)

根据推荐结果生成最小化 Tableau Workbook XML（.twb 骨架）含字段映射 + 标记类型。
骨架不含数据源连接配置（用户需手动绑定数据源）。

TWB 骨架结构：
  <workbook>
    <datasources/>          ← 空占位，用户手动绑定
    <worksheets>
      <worksheet name="Sheet 1">
        <table>
          <view>
            <datasource/>   ← 数据源引用（占位）
            <rows/>         ← 行字段（来自 field_mapping）
            <cols/>         ← 列字段（来自 field_mapping）
            <marks class="{tableau_mark_type}"/>
          </view>
        </table>
      </worksheet>
    </worksheets>
  </workbook>

字段映射规则：
  x → <cols>（维度字段）
  y → <rows>（度量字段，SUM 聚合）
  color → <marks><encoding channel="color">
"""

import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .prompts import CHART_TYPE_TO_TABLEAU_MARK

logger = logging.getLogger(__name__)

# TWB 临时文件存储目录
_TWB_TEMP_DIR = "/tmp/mulan_twb/"
_TWB_EXPIRY_SECONDS = 3600  # 1 小时


class TWBGenerator:
    """
    TWB 骨架生成器。

    支持：
    - 生成符合 Tableau 语法的最小化 TWB XML
    - 临时文件存储 + 签名 URL 提供下载
    - 过期自动清理
    """

    def __init__(self, temp_dir: str = _TWB_TEMP_DIR, expiry_seconds: int = _TWB_EXPIRY_SECONDS):
        self._temp_dir = temp_dir
        self._expiry_seconds = expiry_seconds
        self._ensure_temp_dir()

    # ── Public API ──────────────────────────────────────────────────────────────

    def generate_twb(
        self,
        recommendation: Dict[str, Any],
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        生成 TWB 骨架 XML。

        Args:
            recommendation: 推荐结果（含 chart_type, field_mapping, tableau_mark_type）
            filename: 下载文件名（可选，默认生成）

        Returns:
            {
                "twb_content": str,  # XML 字符串
                "filename": str,
                "download_url": str,
                "expires_at": str (ISO8601),
            }
        """
        chart_type = recommendation.get("chart_type", "bar")
        field_mapping = recommendation.get("field_mapping", {})
        tableau_mark_type = recommendation.get(
            "tableau_mark_type",
            CHART_TYPE_TO_TABLEAU_MARK.get(chart_type, "Bar"),
        )
        suggested_title = recommendation.get("suggested_title", "推荐图表")

        # 构建 TWB XML
        twb_xml = self._build_twb_xml(
            chart_type=chart_type,
            field_mapping=field_mapping,
            mark_type=tableau_mark_type,
            title=suggested_title,
        )

        # 生成文件名
        if not filename:
            safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in suggested_title)
            filename = f"{safe_title[:50]}_{uuid.uuid4().hex[:8]}.twb"

        # 保存临时文件
        download_url, expires_at = self._save_temp_file(filename, twb_xml)

        return {
            "twb_content": twb_xml,
            "filename": filename,
            "download_url": download_url,
            "expires_at": expires_at,
        }

    def get_download_url(self, token: str) -> Optional[str]:
        """
        根据下载 token 获取实际下载 URL（用于验证 + 重定向）。

        token = base64(urlsafe_b64encode(filepath + expiry))
        """
        try:
            import base64

            decoded = base64.urlsafe_b64decode(token.encode()).decode()
            filepath, expiry_str = decoded.rsplit("|", 1)
            expiry = datetime.fromisoformat(expiry_str)

            if datetime.now(timezone.utc) > expiry:
                return None  # 已过期

            if not os.path.isfile(filepath):
                return None

            return f"/api/visualization/export/download/{os.path.basename(filepath)}"
        except Exception:
            return None

    # ── TWB XML 构建 ──────────────────────────────────────────────────────────

    def _build_twb_xml(
        self,
        chart_type: str,
        field_mapping: Dict[str, Any],
        mark_type: str,
        title: str,
    ) -> str:
        """
        构建 TWB XML 骨架。
        """
        x_field = field_mapping.get("x", "")
        y_field = field_mapping.get("y", "")
        color_field = field_mapping.get("color")

        # 根据 chart_type 决定行列分配
        if chart_type in ("line", "area", "scatter"):
            # 时间/连续趋势：x=cols（时间维度），y=rows（度量）
            cols_field = x_field
            rows_field = y_field
        elif chart_type in ("bar", "histogram", "box"):
            # 分类对比：x=rows（分类维度），y=cols（度量）
            cols_field = y_field
            rows_field = x_field
        elif chart_type == "pie":
            # 饼图：category 在 rows，measure 在 cols
            cols_field = y_field
            rows_field = x_field
        else:
            cols_field = x_field
            rows_field = y_field

        # 构建 field 元素
        def make_field(name: str, role: str = "dimension") -> str:
            if not name:
                return ""
            if role == "measure":
                return f'<field name="[{name}]" caption="{name}" type="quantitative" aggregate="SUM" />'
            return f'<field name="[{name}]" caption="{name}" type="{role}" />'

        cols_xml = make_field(cols_field, "dimension") if cols_field else ""
        rows_xml = make_field(rows_field, "measure") if rows_field else ""

        # Color encoding（可选）
        color_xml = ""
        if color_field:
            color_xml = f"""
        <encoding channel="color">
          <field name="[{color_field}]" />
        </encoding>"""

        # 清理 title（XML 转义）
        safe_title = (
            title.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        twb_xml = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook>
  <repository-location id="mulan-viz-agent" revision="1" schema-version="1.0" />
  <datasources>
    <datasource name="[Datasource]" />
  </datasources>
  <worksheets>
    <worksheet name="Sheet 1">
      <table>
        <view>
          <datasources>
            <datasource name="[Datasource]" />
          </datasources>
          <cols>{cols_xml}</cols>
          <rows>{rows_xml}</rows>
          <marks class="{mark_type}">{color_xml}
          </marks>
        </view>
      </table>
    </worksheet>
  </worksheets>
</workbook>
""".strip()

        return twb_xml

    # ── 临时文件管理 ────────────────────────────────────────────────────────────

    def _ensure_temp_dir(self) -> None:
        os.makedirs(self._temp_dir, exist_ok=True)

    def _save_temp_file(self, filename: str, content: str) -> tuple[str, str]:
        """
        保存 TWB 内容到临时文件，返回下载 URL 和过期时间。
        """
        filepath = os.path.join(self._temp_dir, filename)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._expiry_seconds)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        # 生成签名 token（filepath|expiry_iso）
        import base64

        token_payload = f"{filepath}|{expires_at.isoformat()}"
        token = base64.urlsafe_b64encode(token_payload.encode()).decode()

        download_url = f"/api/visualization/export/download/{token}"

        # 调度清理（惰性：下次调用时清理过期文件）
        self._cleanup_expired()

        return download_url, expires_at.isoformat()

    def _cleanup_expired(self) -> None:
        """
        清理过期临时文件（惰性清理）。
        """
        if not os.path.isdir(self._temp_dir):
            return

        now = datetime.now(timezone.utc)
        for fname in os.listdir(self._temp_dir):
            fpath = os.path.join(self._temp_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
                if now - mtime > timedelta(seconds=self._expiry_seconds):
                    os.remove(fpath)
                    logger.debug("TWBGenerator: 清理过期文件 %s", fname)
            except Exception as e:
                logger.warning("TWBGenerator: 清理文件失败 %s: %s", fname, e)
