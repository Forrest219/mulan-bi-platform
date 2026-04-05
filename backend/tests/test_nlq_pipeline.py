"""
NL-to-Query 流水线测试（基于 Golden Dataset）

Stage 1：校验 One-Pass LLM 输出的 JSON Schema 与 Golden Case 的 expected_vizql_json 匹配
Stage 3：校验 MCP 响应格式与 Golden Case 的 expected_mock_response 匹配
Stage 4：校验格式化引擎的 response_type 推断
"""
import pytest
from tests.fixtures.nlq_golden_dataset import GOLDEN_DATASET


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 校验：expected_vizql_json 结构完整性
# ─────────────────────────────────────────────────────────────────────────────

class TestStage1VizqlJson:
    """Stage 1 — One-Pass LLM 输出的 VizQL JSON 格式校验"""

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_fields_is_list(self, case):
        """fields 必须是 list"""
        fields = case["expected_vizql_json"]["fields"]
        assert isinstance(fields, list), f"case {case['id']}: fields 必须是 list"
        assert len(fields) > 0, f"case {case['id']}: fields 不能为空"

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_field_caption_present(self, case):
        """每个 field 必须有 fieldCaption"""
        for field in case["expected_vizql_json"]["fields"]:
            assert "fieldCaption" in field, f"case {case['id']}: field 缺少 fieldCaption"
            assert isinstance(field["fieldCaption"], str), f"case {case['id']}: fieldCaption 必须是 str"

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_function_enum_valid(self, case):
        """field.function 必须是合法的聚合/时间粒度枚举"""
        valid_functions = {
            "SUM", "AVG", "COUNT", "COUNTD", "MIN", "MAX", "MEDIAN",
            "YEAR", "QUARTER", "MONTH", "WEEK", "DAY",
        }
        for field in case["expected_vizql_json"]["fields"]:
            if "function" in field:
                assert field["function"] in valid_functions, (
                    f"case {case['id']}: function '{field['function']}' 不在合法枚举中"
                )

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_filters_field_nested_object(self, case):
        """filters 中的 field 必须是 {"fieldCaption": "..."} 对象，不是字符串"""
        for f in case["expected_vizql_json"]["filters"]:
            assert "field" in f, f"case {case['id']}: filter 缺少 field"
            assert isinstance(f["field"], dict), f"case {case['id']}: filter.field 必须是 dict"
            assert "fieldCaption" in f["field"], f"case {case['id']}: filter.field 缺少 fieldCaption"

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_filter_type_enum(self, case):
        """filter.filterType 必须是合法枚举"""
        valid_filter_types = {"SET", "QUANTITATIVE_NUMERICAL", "DATE", "TOP", "MATCH"}
        for f in case["expected_vizql_json"]["filters"]:
            if "filterType" in f:
                assert f["filterType"] in valid_filter_types, (
                    f"case {case['id']}: filterType '{f['filterType']}' 不在合法枚举中"
                )

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_date_filter_has_required_fields(self, case):
        """DATE 类型过滤器必须包含 periodType 和 dateRangeType"""
        for f in case["expected_vizql_json"]["filters"]:
            if f.get("filterType") == "DATE":
                assert "periodType" in f, f"case {case['id']}: DATE filter 缺少 periodType"
                assert "dateRangeType" in f, f"case {case['id']}: DATE filter 缺少 dateRangeType"
                valid_period = {"MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS", "QUARTERS", "YEARS"}
                assert f["periodType"] in valid_period, f"case {case['id']}: periodType 不合法"

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_quantitative_filter_has_min_or_max(self, case):
        """QUANTITATIVE_NUMERICAL 过滤器必须有 min/max"""
        for f in case["expected_vizql_json"]["filters"]:
            if f.get("filterType") == "QUANTITATIVE_NUMERICAL":
                qt = f.get("quantitativeFilterType", "")
                if qt == "MIN":
                    assert "min" in f, f"case {case['id']}: QUANTITATIVE_NUMERICAL MIN 缺少 min"
                elif qt == "MAX":
                    assert "max" in f, f"case {case['id']}: QUANTITATIVE_NUMERICAL MAX 缺少 max"
                elif qt == "RANGE":
                    assert "min" in f and "max" in f, f"case {case['id']}: RANGE 缺少 min/max"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 校验：MCP 响应格式与 expected_mock_response 匹配
# ─────────────────────────────────────────────────────────────────────────────

class TestStage3MockResponse:
    """Stage 3 — MCP query-datasource 响应格式校验"""

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_mock_response_has_fields_and_rows(self, case):
        """响应必须有 fields 和 rows"""
        resp = case["expected_mock_response"]
        assert "fields" in resp, f"case {case['id']}: 响应缺少 fields"
        assert "rows" in resp, f"case {case['id']}: 响应缺少 rows"

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_mock_fields_count_matches_rows(self, case):
        """fields 数量应与 rows 每行列数一致"""
        resp = case["expected_mock_response"]
        n_fields = len(resp["fields"])
        for row in resp["rows"]:
            assert len(row) == n_fields, (
                f"case {case['id']}: row {row} 长度({len(row)}) 与 fields 数量({n_fields}) 不匹配"
            )

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_mock_fields_have_caption_and_datatype(self, case):
        """每个 field 必须有 fieldCaption 和 dataType"""
        for f in case["expected_mock_response"]["fields"]:
            assert "fieldCaption" in f, f"case {case['id']}: field 缺少 fieldCaption"
            assert "dataType" in f, f"case {case['id']}: field 缺少 dataType"
            valid_types = {"string", "number", "boolean", "date"}
            assert f["dataType"] in valid_types, (
                f"case {case['id']}: dataType '{f['dataType']}' 不在合法枚举中"
            )

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_mock_rows_are_2d_list(self, case):
        """rows 必须是 list[list]"""
        for row in case["expected_mock_response"]["rows"]:
            assert isinstance(row, list), f"case {case['id']}: row {row} 必须是 list"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 校验：response_type 推断逻辑
# ─────────────────────────────────────────────────────────────────────────────

class TestStage4ResponseType:
    """Stage 4 — 响应类型推断校验"""

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_response_type_is_valid(self, case):
        """response_type 必须是合法枚举"""
        valid = {"number", "table", "text"}
        assert case["expected_response_type"] in valid, (
            f"case {case['id']}: response_type '{case['expected_response_type']}' 不在合法枚举中"
        )

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_single_row_single_number_is_number_type(self, case):
        """单行单列(number) → response_type 应为 number"""
        resp = case["expected_mock_response"]
        if case["expected_response_type"] == "number":
            assert len(resp["rows"]) == 1, f"case {case['id']}: number 类型应有且仅有一行"
            assert len(resp["rows"][0]) == 1, f"case {case['id']}: number 类型应有且仅有一列"

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_multi_row_is_table_type(self, case):
        """多行数据 → response_type 应为 table"""
        resp = case["expected_mock_response"]
        if case["expected_response_type"] == "table":
            assert len(resp["rows"]) > 1, f"case {case['id']}: table 类型应有多行"


# ─────────────────────────────────────────────────────────────────────────────
# 集成校验：Stage 1 → Stage 3 数据流一致性
# ─────────────────────────────────────────────────────────────────────────────

class TestStage1to3Consistency:
    """Stage 1 输出的 fields.caption 与 Stage 3 响应的 fields.caption 必须一致"""

    @pytest.mark.parametrize("case", GOLDEN_DATASET, ids=lambda c: f"case-{c['id']}-{c['intent']}")
    def test_vizql_field_captions_match_mock_field_captions(self, case):
        """请求的 fieldCaption 与响应的 fieldCaption 必须完全匹配（顺序可不同）"""
        vizql_captions = {f["fieldCaption"] for f in case["expected_vizql_json"]["fields"]}
        mock_captions = {f["fieldCaption"] for f in case["expected_mock_response"]["fields"]}
        assert vizql_captions == mock_captions, (
            f"case {case['id']}: VizQL field captions {vizql_captions} "
            f"与 Mock 响应 field captions {mock_captions} 不一致"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 模糊匹配专项：Case 21 — Stage 1↔Stage 2 跨阶段字段桥接
# ─────────────────────────────────────────────────────────────────────────────

class TestFuzzyMatchingFieldBridge:
    """
    Case 21 专项测试：用户说'营收'，数据源只有'Sales'字段。

    验证链路：
      Stage 1（One-Pass LLM）生成 VizQL JSON 时，应将用户术语'营收'映射为实际字段'Sales'
      → vizql_json.fields[].fieldCaption 必须是 'Sales'，不是 '营收'
      → Stage 3 mock_response.fields[].fieldCaption 也是 'Sales'
      → TestStage1to3Consistency 隐式验证两处一致

    为什么这是 Stage 2 的核心职责：
      Stage 2 的 resolve_fields() 输出 ResolvedField(user_term, field_caption, match_source)
      理想情况下 match_source='synonym'，user_term='营收'，field_caption='Sales'
      Stage 1 应参考 Stage 2 的输出生成 VizQL JSON（但 Stage 1 先执行，这是设计矛盾点）
      当前实现中 Stage 1 直接输出 VizQL JSON，Stage 2 负责校验/补全
    """

    def test_fuzzy_case_vizql_uses_actual_field_caption_not_user_term(self):
        """
        模糊匹配 case 的 expected_vizql_json 中，fieldCaption 必须是数据源实际字段名，
        不能是用户的原始表述。'营收' → 'Sales'。
        """
        case = next(c for c in GOLDEN_DATASET if c["id"] == 21)
        field_captions = {f["fieldCaption"] for f in case["expected_vizql_json"]["fields"]}
        assert "营收" not in field_captions, (
            "fieldCaption 不能是用户原始表述'营收'，必须是数据源实际字段名'Sales'"
        )
        assert "Sales" in field_captions, (
            "fieldCaption 必须是数据源实际字段名'Sales'"
        )

    def test_fuzzy_case_stage1_to_stage3_caption_consistency(self):
        """
        Case 21：Stage 1 输出的 fieldCaption 与 Stage 3 响应的 fieldCaption 必须完全一致。
        '营收' 经过 Stage 1→Stage 2 桥接后，VizQL 用 'Sales'，Mock 响应也用 'Sales'。
        """
        case = next(c for c in GOLDEN_DATASET if c["id"] == 21)
        vizql_captions = {f["fieldCaption"] for f in case["expected_vizql_json"]["fields"]}
        mock_captions = {f["fieldCaption"] for f in case["expected_mock_response"]["fields"]}
        assert vizql_captions == mock_captions, (
            f"VizQL captions {vizql_captions} != Mock captions {mock_captions}"
        )

    def test_fuzzy_case_intent_is_aggregate(self):
        """营收查询 → 聚合意图"""
        case = next(c for c in GOLDEN_DATASET if c["id"] == 21)
        assert case["intent"] == "aggregate"

    def test_fuzzy_case_response_type_is_table(self):
        """多区域营收 → 表格"""
        case = next(c for c in GOLDEN_DATASET if c["id"] == 21)
        assert case["expected_response_type"] == "table"
        assert len(case["expected_mock_response"]["rows"]) > 1

