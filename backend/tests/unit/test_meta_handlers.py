"""
测试：Meta Handler — NLQ 元信息查询场景（共 10 条产品需求）

覆盖意图：
  - meta_datasource_list  （场景 1）
  - meta_asset_count      （场景 2）
  - meta_field_list       （场景 3）
  - meta_unknown/未实现   （场景 4-10，xfail/skip）

全部通过 mock _mcp_list_datasources / _mcp_get_datasource_metadata 实现，
不依赖真实 Tableau MCP 连接。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：构造最小化的 TableauAsset / Field mock
# ─────────────────────────────────────────────────────────────────────────────

def _make_asset(name: str, luid: str = "luid-001", asset_type: str = "datasource"):
    a = MagicMock()
    a.name = name
    a.datasource_luid = luid
    a.asset_type = asset_type
    a.is_deleted = False
    return a


def _make_field(caption: str, role: str = "dimension", data_type: str = "string"):
    f = MagicMock()
    f.field_caption = caption
    f.role = role
    f.data_type = data_type
    return f


def _make_conn(conn_id: int = 1, name: str = "测试连接", site: str = None):
    c = MagicMock()
    c.id = conn_id
    c.name = name
    c.site = site
    return c


# ─────────────────────────────────────────────────────────────────────────────
# 场景 1：数据源总数查询（meta_datasource_list）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaDatasourceList:
    """场景 1：'咱们现在一共接了多少个数据源？' → meta_datasource_list"""

    @pytest.mark.asyncio
    async def test_mcp_returns_datasource_list_shows_total_count(self):
        """
        场景：MCP 正常返回 3 个数据源列表
        输入：question="咱们现在一共接了多少个数据源？"
        预期：content 包含数字 3，intent == meta_datasource_list
        """
        from app.api.search import _handle_meta_datasource_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        ds_list = [
            {"name": "管理费用", "luid": "luid-001"},
            {"name": "销售明细", "luid": "luid-002"},
            {"name": "人员信息", "luid": "luid-003"},
        ]

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.return_value = ds_list
            result = await _handle_meta_datasource_list_all(
                connections=[mock_conn],
                db=mock_db,
            )

        assert result["intent"] == "meta_datasource_list"
        assert "3" in result["content"], "content 应包含数据源总数 3"
        assert "管理费用" in result["content"]
        assert "销售明细" in result["content"]

    @pytest.mark.asyncio
    async def test_mcp_returns_empty_list_shows_empty_hint(self):
        """
        场景：MCP 正常返回但没有任何数据源
        输入：MCP 返回空列表
        预期：content 提示「暂无已发布的数据源」，intent == meta_datasource_list
        """
        from app.api.search import _handle_meta_datasource_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.return_value = []
            result = await _handle_meta_datasource_list_all(
                connections=[mock_conn],
                db=mock_db,
            )

        assert result["intent"] == "meta_datasource_list"
        assert "暂无" in result["content"]

    @pytest.mark.asyncio
    async def test_mcp_unavailable_returns_error_message(self):
        """
        场景：MCP 不可用（抛出异常）
        输入：_mcp_list_datasources 抛 RuntimeError
        预期：content 提示检查 MCP 配置，intent == meta_datasource_list，不抛异常
        """
        from app.api.search import _handle_meta_datasource_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.side_effect = RuntimeError("MCP 连接失败")
            result = await _handle_meta_datasource_list_all(
                connections=[mock_conn],
                db=mock_db,
            )

        assert result["intent"] == "meta_datasource_list"
        assert "暂时异常" in result["content"] or "管理员" in result["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 场景 2：看板 / 报表统计（meta_asset_count）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaAssetCount:
    """场景 2：'平台上现在有多少个报表在跑？' → meta_asset_count"""

    @pytest.mark.asyncio
    async def test_asset_count_returns_total_across_connections(self):
        """
        场景：单连接下有 2 个 dashboard + 3 个 workbook
        输入：connections=[conn1]，DB count 分别返回 2 / 3
        预期：total=5，content 包含「5」，intent == meta_asset_count
        """
        from app.api.search import _handle_meta_asset_count_all

        conn = _make_conn(conn_id=1, name="主连接", site="default")
        mock_db = MagicMock()

        # 连续两次 count() 调用：先 dashboard=2，后 workbook=3
        mock_db.query.return_value.filter.return_value.count.side_effect = [2, 3]

        result = await _handle_meta_asset_count_all(
            connections=[conn],
            db=mock_db,
        )

        assert result["intent"] == "meta_asset_count"
        assert "5" in result["content"], "content 应包含总数 5"
        assert "2" in result["content"] and "3" in result["content"]

    @pytest.mark.asyncio
    async def test_asset_count_multi_connections_aggregated(self):
        """
        场景：两个连接，连接A（1+2），连接B（3+4）
        输入：connections=[connA, connB]，DB count 依次返回 1,2,3,4
        预期：total=10，content 包含「10」，intent == meta_asset_count
        """
        from app.api.search import _handle_meta_asset_count_all

        conn_a = _make_conn(conn_id=1, name="连接A", site="site-a")
        conn_b = _make_conn(conn_id=2, name="连接B", site="site-b")
        mock_db = MagicMock()

        # 4 次 count 调用：A.dashboard=1, A.workbook=2, B.dashboard=3, B.workbook=4
        mock_db.query.return_value.filter.return_value.count.side_effect = [1, 2, 3, 4]

        result = await _handle_meta_asset_count_all(
            connections=[conn_a, conn_b],
            db=mock_db,
        )

        assert result["intent"] == "meta_asset_count"
        assert "10" in result["content"], "两个连接汇总应得到总数 10"

    @pytest.mark.asyncio
    async def test_asset_count_zero_shows_no_data(self):
        """
        场景：连接下无任何看板
        输入：DB count 均返回 0
        预期：content 包含「0」，intent == meta_asset_count
        """
        from app.api.search import _handle_meta_asset_count_all

        conn = _make_conn(conn_id=1, name="空连接")
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        result = await _handle_meta_asset_count_all(
            connections=[conn],
            db=mock_db,
        )

        assert result["intent"] == "meta_asset_count"
        assert "0" in result["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 场景 3：数据源字段列表（meta_field_list，名称模糊匹配）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaFieldList:
    """场景 3：'「管理费用」那个数据源里具体都有哪些字段？' → meta_field_list"""

    @pytest.mark.asyncio
    async def test_mcp_returns_fields_for_matched_datasource(self):
        """
        场景：MCP list-datasources 返回列表，问题中包含「管理费用」；
              MCP get-datasource-metadata 返回该数据源的字段列表。
        输入：question="管理费用数据源 有什么字段"
        预期：content 包含字段名「部门」「金额」，intent == meta_field_list
        """
        from app.api.search import _handle_meta_field_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        ds_list = [{"name": "管理费用", "luid": "luid-001"}]
        metadata = {
            "datasource": {
                "fields": [
                    {"name": "部门", "role": "DIMENSION", "dataType": "STRING"},
                    {"name": "金额", "role": "MEASURE", "dataType": "REAL"},
                ]
            }
        }

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_list, \
             patch("app.api.search._mcp_get_datasource_metadata", new_callable=AsyncMock) as mock_meta:

            mock_list.return_value = ds_list
            mock_meta.return_value = metadata

            result = await _handle_meta_field_list_all(
                connections=[mock_conn],
                db=mock_db,
                question="管理费用数据源 有什么字段",
            )

        assert result["intent"] == "meta_field_list"
        assert "管理费用" in result["content"]
        assert "部门" in result["content"]
        assert "金额" in result["content"]

    @pytest.mark.asyncio
    async def test_fuzzy_match_selects_longest_name(self):
        """
        场景：数据源列表包含「费用」和「管理费用」，问题包含「管理费用」；
              应优先匹配更长的名称「管理费用」（最长优先匹配策略）。
        输入：question="管理费用有哪些字段"
        预期：_mcp_get_datasource_metadata 被调用时使用「管理费用」的 luid-002
        """
        from app.api.search import _handle_meta_field_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        ds_list = [
            {"name": "费用", "luid": "luid-001"},
            {"name": "管理费用", "luid": "luid-002"},
        ]
        metadata = {
            "datasource": {
                "fields": [{"name": "科目", "role": "DIMENSION", "dataType": "STRING"}]
            }
        }

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_list, \
             patch("app.api.search._mcp_get_datasource_metadata", new_callable=AsyncMock) as mock_meta:

            mock_list.return_value = ds_list
            mock_meta.return_value = metadata

            result = await _handle_meta_field_list_all(
                connections=[mock_conn],
                db=mock_db,
                question="管理费用有哪些字段",
            )

        # 验证调用了正确的 luid（管理费用 = luid-002）
        mock_meta.assert_called_once()
        call_args = mock_meta.call_args
        assert "luid-002" in str(call_args), "应使用最长匹配「管理费用」的 luid-002"
        assert result["intent"] == "meta_field_list"

    @pytest.mark.asyncio
    async def test_no_ds_name_in_question_returns_hint(self):
        """
        场景：MCP 返回数据源列表，但用户问题中没有匹配的数据源名称
        输入：question="这个数据源有什么字段"（无法匹配任何数据源）
        预期：content 提示用户指定数据源，intent == meta_field_list
        """
        from app.api.search import _handle_meta_field_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        ds_list = [{"name": "管理费用", "luid": "luid-001"}]

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = ds_list

            result = await _handle_meta_field_list_all(
                connections=[mock_conn],
                db=mock_db,
                question="这个数据源有什么字段",
            )

        assert result["intent"] == "meta_field_list"
        assert "请告诉" in result["content"] or "数据源" in result["content"]

    @pytest.mark.asyncio
    async def test_mcp_unavailable_returns_mcp_config_error(self):
        """
        场景：用户问「管理费用数据源 有什么字段」，但 MCP list-datasources 抛出异常
        期望：返回检查 MCP 配置的错误提示，intent == meta_field_list

        行为说明：当前实现（重构后）不再有本地 DB fallback，
        MCP 失败时统一返回"获取数据源列表失败，Tableau 连接不可用，请检查 MCP 配置"。
        旧逻辑（有 fallback）已在重构中移除。
        """
        from app.api.search import _handle_meta_field_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.side_effect = RuntimeError("MCP list-datasources 错误 [-32001]: 未找到 Tableau MCP 配置")

            result = await _handle_meta_field_list_all(
                connections=[mock_conn],
                db=mock_db,
                question="管理费用数据源 有什么字段",
            )

        assert result["intent"] == "meta_field_list"
        assert "暂时异常" in result["content"] or "管理员" in result["content"], (
            "MCP 不可用时应返回提示检查 MCP 配置的错误信息"
        )

    @pytest.mark.asyncio
    async def test_mcp_unavailable_field_query_returns_mcp_config_hint(self):
        """
        场景：MCP 失败时的字段查询（通用错误 RuntimeError）
        期望：返回检查 MCP 配置的错误文案，不应有"暂时无法获取"（旧文案已移除）

        行为说明：当前实现中 MCP 失败时统一返回
        "获取数据源列表失败，Tableau 连接不可用，请检查 MCP 配置。"
        """
        from app.api.search import _handle_meta_field_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.side_effect = RuntimeError("MCP error")

            result = await _handle_meta_field_list_all(
                connections=[mock_conn],
                db=mock_db,
                question="管理费用数据源 有什么字段",
            )

        assert result["intent"] == "meta_field_list"
        # 当前实现返回"获取数据源列表失败，Tableau 连接不可用，请检查 MCP 配置。"
        assert "暂时异常" in result["content"] or "管理员" in result["content"]

    @pytest.mark.asyncio
    async def test_mcp_get_metadata_fails_returns_mcp_config_hint(self):
        """
        场景：MCP list-datasources 正常返回「管理费用」，但
              get-datasource-metadata 调用失败。
        期望：错误文案包含"MCP 配置"字样，intent == meta_field_list

        行为说明：当前实现不区分 local_asset_exists，
        get-datasource-metadata 失败时统一返回
        "获取「{ds_name}」字段信息失败，Tableau 连接不可用，请检查 MCP 配置。"
        """
        from app.api.search import _handle_meta_field_list_all

        mock_conn = _make_conn()
        mock_db = MagicMock()

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_list, \
             patch("app.api.search._mcp_get_datasource_metadata", new_callable=AsyncMock) as mock_meta:

            mock_list.return_value = [{"name": "管理费用", "luid": "luid-001"}]
            mock_meta.side_effect = RuntimeError("MCP get-datasource-metadata 失败")

            result = await _handle_meta_field_list_all(
                connections=[mock_conn],
                db=mock_db,
                question="管理费用数据源 有什么字段",
            )

        assert result["intent"] == "meta_field_list"
        assert "暂时异常" in result["content"] or "管理员" in result["content"], (
            f"get-datasource-metadata 失败时应提示检查 MCP 配置，实际：{result['content']}"
        )
        assert "管理费用" in result["content"], "错误提示应包含数据源名称"

    @pytest.mark.asyncio
    async def test_mcp_get_metadata_fails_no_local_asset_returns_mcp_config_hint(self):
        """
        场景：数据源在本地 DB 不存在（local_asset_exists=False）；
              MCP get-datasource-metadata 也抛出异常。
        期望：错误文案包含"MCP 配置"字样，提示用户检查 Tableau 连接。
        """
        from app.api.search import _handle_meta_field_list_all

        mock_conn = _make_conn()

        mock_db = MagicMock()

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_list, \
             patch("app.api.search._mcp_get_datasource_metadata", new_callable=AsyncMock) as mock_meta:

            mock_list.return_value = [{"name": "管理费用", "luid": "luid-002"}]
            mock_meta.side_effect = RuntimeError("MCP get-datasource-metadata 失败")

            with patch("app.api.search.TableauAsset") as mock_ta_cls:
                mock_session = MagicMock()
                mock_session.query.return_value.filter.return_value.first.return_value = None

                with patch("services.tableau.models.TableauDatabase") as mock_tdb_cls:
                    mock_tdb = MagicMock()
                    mock_tdb.session = mock_session
                    mock_tdb_cls.return_value = mock_tdb

                    result = await _handle_meta_field_list_all(
                        connections=[mock_conn],
                        db=mock_db,
                        question="管理费用数据源 有什么字段",
                    )

        assert result["intent"] == "meta_field_list"
        assert "暂时异常" in result["content"] or "管理员" in result["content"], (
            f"local_asset_exists=False 时，错误文案应包含「MCP 配置」，实际内容：{result['content']}"
        )
        assert "字段同步" not in result["content"], (
            "local_asset_exists=False 时，不应提示字段同步问题"
        )

    @pytest.mark.asyncio
    async def test_mcp_returns_error_field_raises_runtime_error(self):
        """
        MCP 响应包含 error 字段时，_mcp_list_datasources 应抛出 RuntimeError（不静默返回空）
        回归：修复前此函数会返回 []，导致真实错误被吞掉
        """
        import httpx
        from app.api.search import _mcp_list_datasources

        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32001, "message": "未找到 Tableau MCP 配置"},
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            init_resp = MagicMock()
            init_resp.json.return_value = {"jsonrpc": "2.0", "result": {}}

            notif_resp = MagicMock()
            notif_resp.json.return_value = {"jsonrpc": "2.0", "result": None}

            error_resp = MagicMock()
            error_resp.json.return_value = error_response

            mock_client.post = AsyncMock(side_effect=[init_resp, notif_resp, error_resp])

            with pytest.raises(RuntimeError, match="MCP list-datasources 错误"):
                await _mcp_list_datasources("http://localhost:8000/tableau-mcp", "", "", "", "")


# ─────────────────────────────────────────────────────────────────────────────
# 场景 4：查询数据源对应的物理表名（当前不支持）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaPhysicalTableName:
    """
    场景 4：'「管理费用」数据源对应后台的物理表叫什么名字？'
    当前意图路由不支持此查询（MCP 元数据中不直接返回物理表名），
    classify_meta_intent 预期返回 meta_unknown 或 meta_field_list。
    """

    @pytest.mark.xfail(
        reason=(
            "当前 MCP get-datasource-metadata 返回的字段结构不包含 physicalTableName，"
            "handle_meta_query_all 没有 meta_physical_table 分支，"
            "此场景需产品 + 后端确认是否通过 VizQL API 或 Metadata API 实现。"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_query_physical_table_name_returns_table_name(self):
        """
        场景：用户询问「管理费用」数据源在后台对应的物理表名
        输入：question="管理费用数据源对应后台的物理表叫什么名字"
        预期行为（待实现）：
          - intent 应为 meta_physical_table 或 meta_field_list
          - content 包含实际物理表名（如 dim_expense / fact_mgmt_cost 等）
        当前状态：不支持，此测试标记为 xfail
        """
        from app.api.search import handle_meta_query_all

        mock_db = MagicMock()
        mock_user = {"id": 1, "role": "analyst"}

        # 占位：真实实现需要 MCP metadata 接口支持返回 physicalTable 字段
        result = await handle_meta_query_all(
            meta_intent="meta_physical_table",
            db=mock_db,
            user=mock_user,
            question="管理费用数据源对应后台的物理表叫什么名字",
        )

        # 待实现后填充具体断言
        assert "physicalTable" in result or "物理表" in result["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 场景 5：查询使用了某数据源的看板和报表（当前不支持）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaDatasourceUsage:
    """
    场景 5：'都有哪些看板和报表是用了「管理费用」这个数据源的？'
    意图：meta_datasource_usage（当前未实现）
    """

    @pytest.mark.xfail(
        reason=(
            "handle_meta_query_all 中没有 meta_datasource_usage 分支；"
            "需要 Tableau Metadata API 的 workbooksConnection 查询支持，"
            "或通过本地 DB 关联 tableau_assets 表中 datasource_luid 字段来实现反向追溯。"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_datasource_usage_returns_workbook_list(self):
        """
        场景：查询哪些看板 / 报表引用了「管理费用」数据源
        输入：question="哪些看板用了管理费用这个数据源"
        预期行为（待实现）：
          - intent == meta_datasource_usage
          - content 列出引用该数据源的 workbook / dashboard 名称列表
        当前状态：不支持，此测试标记为 xfail
        """
        from app.api.search import handle_meta_query_all

        mock_db = MagicMock()
        mock_user = {"id": 1, "role": "analyst"}

        result = await handle_meta_query_all(
            meta_intent="meta_datasource_usage",
            db=mock_db,
            user=mock_user,
            question="哪些看板用了管理费用这个数据源",
        )

        assert result["intent"] == "meta_datasource_usage"
        assert "管理费用" in result["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 场景 6：最近一个月新增的数据源（当前不支持）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaDatasourceRecent:
    """
    场景 6：'最近这一个月，新增加了哪些数据源？'
    意图：meta_datasource_recent（当前未实现）
    """

    @pytest.mark.xfail(
        reason=(
            "当前 MCP list-datasources 接口不返回 createdAt 时间戳，"
            "本地 DB 的 tableau_assets 表没有按创建时间过滤的索引，"
            "需要 Tableau REST API 的 /datasources?filter=createdAt:gte:... 支持。"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_recently_added_datasources_within_one_month(self):
        """
        场景：查询最近一个月内新增的数据源
        输入：question="最近这一个月新增加了哪些数据源"
        预期行为（待实现）：
          - intent == meta_datasource_recent
          - content 包含按 createdAt 过滤后的数据源列表
          - 时间范围：当前时间往前推 30 天
        当前状态：不支持，此测试标记为 xfail
        """
        from app.api.search import handle_meta_query_all

        mock_db = MagicMock()
        mock_user = {"id": 1, "role": "analyst"}

        result = await handle_meta_query_all(
            meta_intent="meta_datasource_recent",
            db=mock_db,
            user=mock_user,
            question="最近这一个月新增加了哪些数据源",
        )

        assert result["intent"] == "meta_datasource_recent"
        assert "数据源" in result["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 场景 7：过去一周谁动过哪些数据源（当前不支持）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaDatasourceChangeLog:
    """
    场景 7：'过去这一周，谁动过哪些数据源？'
    意图：meta_datasource_recent 或 meta_change_log（当前未实现）
    """

    @pytest.mark.xfail(
        reason=(
            "需要 Tableau 审计日志（Audit Events API）或平台自身操作日志表支持，"
            "当前系统不记录数据源变更的操作人信息。"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_datasource_change_log_last_week(self):
        """
        场景：查询过去 7 天内哪些用户修改了哪些数据源
        输入：question="过去这一周谁动过哪些数据源"
        预期行为（待实现）：
          - intent == meta_change_log 或 meta_datasource_recent
          - content 包含操作人 + 数据源名称 + 操作时间的列表
        当前状态：不支持，此测试标记为 xfail
        """
        from app.api.search import handle_meta_query_all

        mock_db = MagicMock()
        mock_user = {"id": 1, "role": "analyst"}

        result = await handle_meta_query_all(
            meta_intent="meta_change_log",
            db=mock_db,
            user=mock_user,
            question="过去这一周谁动过哪些数据源",
        )

        assert "intent" in result
        assert "数据源" in result["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 场景 8：占用空间最大的前 10 个数据源（当前不支持）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaDatasourceSize:
    """
    场景 8：'占用空间最大的前 10 个数据源是哪几个？'
    意图：meta_datasource_size（当前未实现）
    """

    @pytest.mark.xfail(
        reason=(
            "Tableau MCP list-datasources 响应不包含数据源磁盘占用 size 字段；"
            "需要 Tableau REST API /sites/{id}/datasources 返回 size 属性，"
            "或通过 Tableau Server Admin 视图查询。"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_top10_datasources_by_size(self):
        """
        场景：查询占用磁盘空间最大的前 10 个数据源
        输入：question="占用空间最大的前10个数据源是哪几个"
        预期行为（待实现）：
          - intent == meta_datasource_size
          - content 按 size 降序列出前 10 个数据源名称及大小
        当前状态：不支持，此测试标记为 xfail
        """
        from app.api.search import handle_meta_query_all

        mock_db = MagicMock()
        mock_user = {"id": 1, "role": "analyst"}

        result = await handle_meta_query_all(
            meta_intent="meta_datasource_size",
            db=mock_db,
            user=mock_user,
            question="占用空间最大的前10个数据源是哪几个",
        )

        assert result["intent"] == "meta_datasource_size"
        assert "数据源" in result["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 场景 9：语义信息不完整的数据源（部分支持，已有 meta_semantic_quality）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaSemanticQuality:
    """
    场景 9：'哪些数据源的备注和定义没写全，语义信息不完整的？'
    意图：meta_semantic_quality（已实现 _handle_meta_semantic_quality_all）

    注：当前实现检查 tableau_field_semantics 中 semantic_definition 为空或
    status 为 draft/ai_generated 的字段，而非整个数据源粒度。
    若需"数据源粒度"统计（而非字段粒度），仍需扩展。
    """

    @pytest.mark.asyncio
    async def test_semantic_quality_returns_incomplete_fields(self):
        """
        场景：连接下有语义配置不完善的字段
        输入：DB 查询返回 2 条 semantic_definition 为空的字段记录
        预期：content 提示存在不完善项，intent == meta_semantic_quality
        """
        from app.api.search import _handle_meta_semantic_quality

        mock_db = MagicMock()

        field_a = MagicMock()
        field_a.semantic_definition = ""
        field_a.status = "draft"
        field_a.semantic_name_zh = "管理费用科目"
        field_a.semantic_name = "subject"
        field_a.tableau_field_id = "field-001"

        field_b = MagicMock()
        field_b.semantic_definition = None
        field_b.status = "ai_generated"
        field_b.semantic_name_zh = None
        field_b.semantic_name = "dept"
        field_b.tableau_field_id = "field-002"

        mock_db.query.return_value.filter.return_value.all.return_value = [field_a, field_b]

        with patch("app.api.search.TableauFieldSemantics", create=True):
            from services.semantic_maintenance.models import TableauFieldSemantics
            with patch("app.api.search.TableauFieldSemantics", TableauFieldSemantics, create=True):
                # 直接 mock db.query(...).filter(...).all() 返回值
                result = await _handle_meta_semantic_quality(
                    connection_id=1,
                    db=mock_db,
                )

        assert result["intent"] == "meta_semantic_quality"
        assert "2" in result["content"], "应报告 2 处不完善"

    @pytest.mark.asyncio
    async def test_semantic_quality_all_complete_returns_ok_message(self):
        """
        场景：所有字段语义配置完善（无 draft / 空 definition）
        预期：content 提示配置较为完善，intent == meta_semantic_quality
        """
        from app.api.search import _handle_meta_semantic_quality

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        result = await _handle_meta_semantic_quality(
            connection_id=1,
            db=mock_db,
        )

        assert result["intent"] == "meta_semantic_quality"
        assert "完善" in result["content"]

    @pytest.mark.skip(
        reason=(
            "当前 meta_semantic_quality 是字段粒度（检查 tableau_field_semantics 表），"
            "若产品需要数据源粒度的完整性汇总（即哪些整个数据源的描述缺失），"
            "需要额外扩展逻辑后再补充本用例。"
        )
    )
    @pytest.mark.asyncio
    async def test_datasource_level_semantic_completeness(self):
        """
        场景：查询哪些数据源整体的语义备注和定义缺失（数据源粒度，非字段粒度）
        输入：question="哪些数据源的备注和定义没写全"
        预期行为（待实现）：
          - content 列出缺少 description / 备注的数据源名称
          - intent == meta_semantic_quality
        当前状态：跳过（skip），等产品确认口径后实现
        """
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 场景 10：重名或字段定义冲突的数据源（当前不支持）
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaDatasourceDuplicateCheck:
    """
    场景 10：'有没有哪些数据源是重名或者字段定义对不上的？'
    意图：meta_datasource_duplicate（当前未实现）
    """

    @pytest.mark.xfail(
        reason=(
            "当前没有跨数据源的名称去重或字段定义一致性检查逻辑；"
            "需要对 tableau_assets 表按 name 聚合查重，"
            "以及对 tableau_field_semantics 按字段名聚合比较 semantic_definition 差异。"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_duplicate_datasource_names_detected(self):
        """
        场景：检查是否存在重名数据源或字段定义互相矛盾的数据源
        输入：question="有没有重名或字段定义对不上的数据源"
        预期行为（待实现）：
          - intent == meta_datasource_duplicate 或 meta_semantic_quality
          - content 列出重名的数据源名称对，及冲突的字段定义摘要
        当前状态：不支持，此测试标记为 xfail
        """
        from app.api.search import handle_meta_query_all

        mock_db = MagicMock()
        mock_user = {"id": 1, "role": "analyst"}

        result = await handle_meta_query_all(
            meta_intent="meta_datasource_duplicate",
            db=mock_db,
            user=mock_user,
            question="有没有重名或字段定义对不上的数据源",
        )

        assert result["intent"] == "meta_datasource_duplicate"


# ─────────────────────────────────────────────────────────────────────────────
# 禁止出现的系统错误回复（Bad Response 回归测试）
#
# 这些错误文案曾在真实交互中出现，属于不可接受的用户体验。
# 任何 meta handler 的返回值都不应包含以下字符串。
# ─────────────────────────────────────────────────────────────────────────────

BAD_RESPONSES = [
    # 全局异常处理器兜底，不应暴露给用户
    "服务器内部错误",
    # 参数校验错误，不应作为 NLQ 回复
    "请指定数据源（datasource_luid 或 connection_id）",
    # 技术性错误文案，不应暴露内部系统名称给用户
    "请检查 MCP 配置",
]


def assert_no_bad_response(content: str):
    """断言 content 中不含任何禁止出现的系统错误文案。"""
    for bad in BAD_RESPONSES:
        assert bad not in content, (
            f"回复中出现了禁止的系统错误文案：\n"
            f"  实际回复：{content[:200]}\n"
            f"  禁止文案：{bad}"
        )


class TestBadResponseRegression:
    """
    禁止出现的错误回复回归测试。

    这些错误曾在真实用户交互中出现（2026-04-19），
    记录在错题本中。任何 meta handler 返回值不得包含这些文案。
    """

    @pytest.mark.asyncio
    async def test_datasource_list_no_system_error_on_mcp_success(self):
        """MCP 正常时，数据源列表查询不能出现系统错误文案。"""
        from app.api.search import _handle_meta_datasource_list_all

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.return_value = [{"name": "管理费用", "luid": "luid-001"}]
            result = await _handle_meta_datasource_list_all(
                connections=[_make_conn()], db=MagicMock()
            )

        assert_no_bad_response(result["content"])

    @pytest.mark.asyncio
    async def test_field_list_no_system_error_on_mcp_success(self):
        """MCP 正常时，字段查询不能出现系统错误文案。"""
        from app.api.search import _handle_meta_field_list_all

        ds_list = [{"name": "管理费用数据源", "luid": "luid-001"}]
        metadata = {"datasource": {"id": "luid-001", "name": "管理费用数据源",
                                    "fields": [{"name": "金额"}, {"name": "部门"}]}}

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_ds, \
             patch("app.api.search._mcp_get_datasource_metadata", new_callable=AsyncMock) as mock_meta:
            mock_ds.return_value = ds_list
            mock_meta.return_value = metadata
            result = await _handle_meta_field_list_all(
                connections=[_make_conn()], db=MagicMock(),
                question="管理费用数据源 有什么字段",
            )

        assert_no_bad_response(result["content"])

    @pytest.mark.asyncio
    async def test_datasource_list_no_system_error_on_mcp_failure(self):
        """
        MCP 不可用时，回复应说明原因，不得出现「服务器内部错误」。
        降级回复必须是有意义的提示，不是原始异常堆栈。
        """
        from app.api.search import _handle_meta_datasource_list_all

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.side_effect = RuntimeError("MCP -32001: 未找到 Tableau MCP 配置")
            result = await _handle_meta_datasource_list_all(
                connections=[_make_conn()], db=MagicMock()
            )

        assert_no_bad_response(result["content"])
        # 降级回复不能是空的
        assert len(result["content"]) > 10

    @pytest.mark.asyncio
    async def test_field_list_no_system_error_on_mcp_failure(self):
        """
        MCP 不可用时，字段查询不得出现「服务器内部错误」或「请指定数据源」。
        """
        from app.api.search import _handle_meta_field_list_all

        with patch("app.api.search._mcp_list_datasources", new_callable=AsyncMock) as mock_mcp:
            mock_mcp.side_effect = RuntimeError("MCP -32001: 未找到 Tableau MCP 配置")
            result = await _handle_meta_field_list_all(
                connections=[_make_conn()], db=MagicMock(),
                question="管理费用数据源 有什么字段",
            )

        assert_no_bad_response(result["content"])
        assert len(result["content"]) > 10
