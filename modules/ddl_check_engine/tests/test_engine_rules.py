"""
DDL Check Engine 单元测试

覆盖范围：
- 5 条规则各自独立测试（合规 / 违规 / 边界）
- 评分算法公式验证（Score = 100 - High*20 - Medium*5 - Low*1，clamp [0,100]）
- 整体判定逻辑（passed / executable / score）
- 解析失败的降级处理

重要约束（来自解析器实现）：
  _extract_columns 的正则要求列定义括号后必须跟 ENGINE/CHARSET/USER/PROPERTIES 关键字，
  否则列无法被提取。因此所有测试 DDL 均以 ) ENGINE=InnoDB; 结尾。
"""

import sys
import os

# 确保在任意工作目录下均可 import 引擎包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from ddl_check_engine.engine import DDLCheckEngine, CheckResult
from ddl_check_engine.rules import (
    TableNamingRule,
    ColumnCommentRule,
    AmountTypeRule,
    CreateTimeRule,
    UpdateTimeRule,
    RiskLevel,
    get_default_rules,
)
from ddl_check_engine.parser import DDLParser


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def make_engine(*rules):
    """用指定规则集构造引擎，方便隔离单条规则测试。"""
    return DDLCheckEngine(rules=list(rules))


def rule_ids(issues: list) -> list:
    """从 issues dict 列表中提取 rule_id 列表。"""
    return [i["rule_id"] for i in issues]


def risk_levels_list(issues: list) -> list:
    return [i["risk_level"] for i in issues]


def parse_ddl(ddl: str):
    """解析并断言 DDL 成功。"""
    table = DDLParser.parse(ddl)
    assert table is not None, f"DDL 解析失败: {ddl[:80]}"
    return table


# ---------------------------------------------------------------------------
# RULE_001: 表命名规范（High）
# ---------------------------------------------------------------------------

class TestTableNamingRule:
    rule = TableNamingRule()

    def _check(self, ddl: str):
        return self.rule.check(parse_ddl(ddl))

    def test_valid_name(self):
        """全小写字母加下划线，合规。"""
        ddl = "CREATE TABLE order_detail (id BIGINT COMMENT '主键') ENGINE=InnoDB;"
        assert self._check(ddl) == []

    def test_valid_name_with_numbers(self):
        """小写字母开头，包含数字，合规。"""
        ddl = "CREATE TABLE dim_user2024 (id BIGINT COMMENT '主键') ENGINE=InnoDB;"
        assert self._check(ddl) == []

    def test_uppercase_name(self):
        """表名含大写字母，违规（RULE_001 / High）。"""
        ddl = "CREATE TABLE OrderDetail (id BIGINT COMMENT '主键') ENGINE=InnoDB;"
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_001"
        assert issues[0].risk_level == RiskLevel.HIGH
        assert issues[0].object_type == "table"

    def test_name_exactly_64_chars_is_compliant(self):
        """长度恰好 64 字符，不触发长度违规。"""
        name = "a" * 64
        ddl = f"CREATE TABLE {name} (id BIGINT COMMENT '主键') ENGINE=InnoDB;"
        issues = self._check(ddl)
        length_issues = [i for i in issues if "长度" in i.description]
        assert length_issues == []

    def test_name_65_chars_violates_length(self):
        """长度 65 字符，超限，触发 RULE_001 长度违规。"""
        name = "a" * 65
        ddl = f"CREATE TABLE {name} (id BIGINT COMMENT '主键') ENGINE=InnoDB;"
        issues = self._check(ddl)
        length_issues = [i for i in issues if "长度" in i.description]
        assert len(length_issues) == 1
        assert length_issues[0].rule_id == "RULE_001"
        assert length_issues[0].risk_level == RiskLevel.HIGH

    def test_name_uppercase_and_too_long_yields_two_issues(self):
        """同时超长且含大写，应产生 2 个 RULE_001 问题。"""
        name = "A" * 65
        ddl = f"CREATE TABLE {name} (id BIGINT COMMENT '主键') ENGINE=InnoDB;"
        issues = self._check(ddl)
        assert len(issues) == 2
        assert all(i.rule_id == "RULE_001" for i in issues)
        assert all(i.risk_level == RiskLevel.HIGH for i in issues)


# ---------------------------------------------------------------------------
# RULE_002: 字段必须有注释（High）
# ---------------------------------------------------------------------------

class TestColumnCommentRule:
    rule = ColumnCommentRule()

    def _check(self, ddl: str):
        return self.rule.check(parse_ddl(ddl))

    def test_all_columns_have_comment(self):
        """所有字段均有注释，合规。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            create_time DATETIME COMMENT '创建时间'
        ) ENGINE=InnoDB;"""
        assert self._check(ddl) == []

    def test_one_column_missing_comment(self):
        """一个字段缺少注释，违规（RULE_002 / High）。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            status INT
        ) ENGINE=InnoDB;"""
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_002"
        assert issues[0].risk_level == RiskLevel.HIGH
        assert issues[0].object_type == "column"
        assert issues[0].object_name == "status"

    def test_multiple_columns_missing_comment(self):
        """多个字段缺注释，每列产生一条 RULE_002 问题。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT,
            status INT,
            remark VARCHAR(200)
        ) ENGINE=InnoDB;"""
        issues = self._check(ddl)
        missing = {i.object_name for i in issues}
        assert missing == {"id", "status", "remark"}
        assert all(i.rule_id == "RULE_002" for i in issues)
        assert all(i.risk_level == RiskLevel.HIGH for i in issues)

    def test_empty_comment_string_is_violation(self):
        """空字符串注释等同于没有注释，触发违规。"""
        ddl = "CREATE TABLE t (id BIGINT COMMENT '') ENGINE=InnoDB;"
        issues = self._check(ddl)
        assert any(i.object_name == "id" for i in issues)
        assert all(i.rule_id == "RULE_002" for i in issues)

    def test_whitespace_only_comment_is_violation(self):
        """纯空白注释等同于没有注释，触发违规。"""
        ddl = "CREATE TABLE t (id BIGINT COMMENT '   ') ENGINE=InnoDB;"
        issues = self._check(ddl)
        assert any(i.object_name == "id" for i in issues)
        assert all(i.rule_id == "RULE_002" for i in issues)


# ---------------------------------------------------------------------------
# RULE_003: 金额字段类型（Medium）
# ---------------------------------------------------------------------------

class TestAmountTypeRule:
    rule = AmountTypeRule()

    def _check(self, ddl: str):
        return self.rule.check(parse_ddl(ddl))

    def test_decimal_with_precision_is_compliant(self):
        """DECIMAL(18,2) 金额字段，合规。"""
        ddl = "CREATE TABLE t (order_amount DECIMAL(18,2) COMMENT '金额') ENGINE=InnoDB;"
        assert self._check(ddl) == []

    def test_float_amount_field_violates(self):
        """FLOAT 金额字段，违规（RULE_003 / Medium）。"""
        ddl = "CREATE TABLE t (order_amount FLOAT COMMENT '金额') ENGINE=InnoDB;"
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_003"
        assert issues[0].risk_level == RiskLevel.MEDIUM
        assert issues[0].object_name == "order_amount"

    def test_double_amount_field_violates(self):
        """DOUBLE 金额字段，违规。"""
        ddl = "CREATE TABLE t (total_price DOUBLE COMMENT '总价') ENGINE=InnoDB;"
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_003"
        assert issues[0].object_name == "total_price"

    def test_decimal_without_precision_violates(self):
        """DECIMAL 无精度说明，违规，描述含"精度"。"""
        ddl = "CREATE TABLE t (fee_amount DECIMAL COMMENT '手续费') ENGINE=InnoDB;"
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_003"
        assert "精度" in issues[0].description

    def test_non_amount_field_with_float_is_compliant(self):
        """字段名不含金额关键词，不触发 RULE_003。"""
        ddl = "CREATE TABLE t (ratio FLOAT COMMENT '比率') ENGINE=InnoDB;"
        assert self._check(ddl) == []

    def test_bigint_amount_field_is_compliant(self):
        """金额字段用 BIGINT（分单位存储），不触发 RULE_003。"""
        ddl = "CREATE TABLE t (order_amount BIGINT COMMENT '金额（分）') ENGINE=InnoDB;"
        assert self._check(ddl) == []

    def test_all_amount_keywords_are_detected(self):
        """7 个金额关键词 amount/price/cost/total/money/fee/balance 均被识别。"""
        keywords = ["amount", "price", "cost", "total", "money", "fee", "balance"]
        for kw in keywords:
            ddl = f"CREATE TABLE t (col_{kw} FLOAT COMMENT '测试') ENGINE=InnoDB;"
            issues = self._check(ddl)
            assert any(i.rule_id == "RULE_003" for i in issues), \
                f"关键词 '{kw}' 未被 RULE_003 识别"


# ---------------------------------------------------------------------------
# RULE_004: 必须包含 create_time（High）
# ---------------------------------------------------------------------------

class TestCreateTimeRule:
    rule = CreateTimeRule()

    def _check(self, ddl: str):
        return self.rule.check(parse_ddl(ddl))

    def test_has_create_time(self):
        """含 create_time 字段，合规。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            create_time DATETIME COMMENT '创建时间'
        ) ENGINE=InnoDB;"""
        assert self._check(ddl) == []

    def test_missing_create_time_violates(self):
        """缺 create_time 字段，违规（RULE_004 / High）。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            update_time DATETIME COMMENT '更新时间'
        ) ENGINE=InnoDB;"""
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_004"
        assert issues[0].risk_level == RiskLevel.HIGH
        assert issues[0].object_type == "table"

    def test_create_time_case_insensitive(self):
        """CREATE_TIME 大写也被识别为满足规则（字段名比较不区分大小写）。"""
        ddl = "CREATE TABLE t (CREATE_TIME DATETIME COMMENT '创建时间') ENGINE=InnoDB;"
        assert self._check(ddl) == []

    def test_last_create_time_does_not_satisfy_rule(self):
        """last_create_time 不等于 create_time，仍触发 RULE_004。"""
        ddl = """CREATE TABLE t (
            last_create_time DATETIME COMMENT '最后创建时间'
        ) ENGINE=InnoDB;"""
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_004"


# ---------------------------------------------------------------------------
# RULE_005: 必须包含 update_time（High）
# ---------------------------------------------------------------------------

class TestUpdateTimeRule:
    rule = UpdateTimeRule()

    def _check(self, ddl: str):
        return self.rule.check(parse_ddl(ddl))

    def test_has_update_time(self):
        """含 update_time 字段，合规。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            update_time DATETIME COMMENT '更新时间'
        ) ENGINE=InnoDB;"""
        assert self._check(ddl) == []

    def test_missing_update_time_violates(self):
        """缺 update_time 字段，违规（RULE_005 / High）。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            create_time DATETIME COMMENT '创建时间'
        ) ENGINE=InnoDB;"""
        issues = self._check(ddl)
        assert len(issues) == 1
        assert issues[0].rule_id == "RULE_005"
        assert issues[0].risk_level == RiskLevel.HIGH

    def test_update_time_case_insensitive(self):
        """UPDATE_TIME 大写也被识别为满足规则。"""
        ddl = "CREATE TABLE t (UPDATE_TIME DATETIME COMMENT '更新时间') ENGINE=InnoDB;"
        assert self._check(ddl) == []


# ---------------------------------------------------------------------------
# 评分算法验证
# Score = 100 - High*20 - Medium*5 - Low*1，clamp [0, 100]
# ---------------------------------------------------------------------------

class TestScoreCalculation:

    def _run(self, ddl: str) -> CheckResult:
        return DDLCheckEngine().check(ddl)

    def test_perfect_score_100(self):
        """完全合规：score=100，passed=True，executable=True。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT NOT NULL COMMENT '主键',
            create_time DATETIME COMMENT '创建时间',
            update_time DATETIME COMMENT '更新时间'
        ) ENGINE=InnoDB;"""
        result = self._run(ddl)
        assert result.score == 100
        assert result.passed is True
        assert result.executable is True

    def test_one_high_issue_scores_80(self):
        """1 个 High：100 - 1*20 = 80，但含 High，executable=False，passed=False。"""
        # 缺 update_time → RULE_005(High)，其余满足
        ddl = """CREATE TABLE order_detail (
            id BIGINT NOT NULL COMMENT '主键',
            create_time DATETIME COMMENT '创建时间'
        ) ENGINE=InnoDB;"""
        result = self._run(ddl)
        assert result.score == 80
        assert result.executable is False
        assert result.passed is False

    def test_two_high_issues_scores_60(self):
        """2 个 High：100 - 2*20 = 60，含 High 不可执行。"""
        # 缺 create_time(RULE_004) + 缺 update_time(RULE_005)
        ddl = """CREATE TABLE order_detail (
            id BIGINT NOT NULL COMMENT '主键'
        ) ENGINE=InnoDB;"""
        result = self._run(ddl)
        assert result.score == 60
        assert result.executable is False

    def test_three_high_issues_scores_40(self):
        """3 个 High：100 - 3*20 = 40。"""
        # 表名大写(RULE_001) + 缺 create_time(RULE_004) + 缺 update_time(RULE_005)
        ddl = """CREATE TABLE OrderDetail (
            id BIGINT NOT NULL COMMENT '主键'
        ) ENGINE=InnoDB;"""
        result = self._run(ddl)
        assert result.score == 40
        assert result.executable is False

    def test_one_medium_issue_scores_95(self):
        """1 个 Medium：100 - 1*5 = 95，passed=True，executable=True。"""
        # 金额字段 FLOAT(RULE_003 Medium)，其余 High 规则全满足
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            order_amount FLOAT COMMENT '订单金额',
            create_time DATETIME COMMENT '创建时间',
            update_time DATETIME COMMENT '更新时间'
        ) ENGINE=InnoDB;"""
        result = self._run(ddl)
        assert result.score == 95
        assert result.passed is True
        assert result.executable is True

    def test_five_medium_issues_scores_75(self):
        """5 个 Medium（仅 AmountTypeRule）：100 - 5*5 = 75，executable=True，passed=False。"""
        engine = make_engine(AmountTypeRule())
        ddl = """CREATE TABLE t (
            col_amount_1 FLOAT COMMENT '金额1',
            col_amount_2 FLOAT COMMENT '金额2',
            col_amount_3 FLOAT COMMENT '金额3',
            col_amount_4 FLOAT COMMENT '金额4',
            col_amount_5 FLOAT COMMENT '金额5'
        ) ENGINE=InnoDB;"""
        result = engine.check(ddl)
        assert result.score == 75
        assert result.executable is True
        assert result.passed is False

    def test_eight_medium_issues_scores_60_executable(self):
        """8 个 Medium：100 - 8*5 = 60，score=60，executable=True，passed=False。"""
        engine = make_engine(AmountTypeRule())
        cols = "\n".join(
            [f"    col_amount_{i} FLOAT COMMENT '金额{i}'," for i in range(1, 9)]
        ).rstrip(",")
        ddl = f"CREATE TABLE t (\n{cols}\n) ENGINE=InnoDB;"
        result = engine.check(ddl)
        assert result.score == 60
        assert result.executable is True
        assert result.passed is False

    def test_score_clamped_to_zero(self):
        """6+ 个 High 问题时 score 被 clamp 到 0。

        构造：表名大写(1) + 3 个无注释字段(3) + 缺 create_time(1) + 缺 update_time(1) = 6 High
        score = 100 - 6*20 = -20 → clamp → 0
        """
        ddl = """CREATE TABLE BadName (
            col1 INT,
            col2 INT,
            col3 INT
        ) ENGINE=InnoDB;"""
        result = self._run(ddl)
        assert result.score == 0
        assert result.summary["High"] == 6
        assert result.executable is False

    def test_summary_counts_match_issues(self):
        """summary 字典与 issues 列表中各等级计数一致。"""
        ddl = """CREATE TABLE OrderDetail (
            order_amount FLOAT,
            create_time DATETIME COMMENT '创建时间'
        ) ENGINE=InnoDB;"""
        result = self._run(ddl)
        high = sum(1 for i in result.issues if i["risk_level"] == "High")
        medium = sum(1 for i in result.issues if i["risk_level"] == "Medium")
        low = sum(1 for i in result.issues if i["risk_level"] == "Low")
        assert result.summary["High"] == high
        assert result.summary["Medium"] == medium
        assert result.summary["Low"] == low


# ---------------------------------------------------------------------------
# 整体判定逻辑
# ---------------------------------------------------------------------------

class TestOverallJudgment:

    def test_fully_compliant_ddl(self):
        """完全合规：passed=True，executable=True，score=100，issues=[]。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT NOT NULL COMMENT '主键ID',
            order_no VARCHAR(64) NOT NULL COMMENT '订单号',
            order_amount DECIMAL(18,2) COMMENT '订单金额',
            create_time DATETIME NOT NULL COMMENT '创建时间',
            update_time DATETIME NOT NULL COMMENT '更新时间',
            PRIMARY KEY (id)
        ) ENGINE=InnoDB COMMENT='订单明细表';"""
        result = DDLCheckEngine().check(ddl)
        assert result.passed is True
        assert result.executable is True
        assert result.score == 100
        assert result.issues == []

    def test_high_violation_makes_not_executable(self):
        """含 High 违规时：executable=False，passed=False。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键'
        ) ENGINE=InnoDB;"""
        result = DDLCheckEngine().check(ddl)
        assert result.executable is False
        assert result.passed is False
        assert any(i["risk_level"] == "High" for i in result.issues)

    def test_score_60_to_79_executable_but_not_passed(self):
        """score 在 [60,79] 区间：executable=True，passed=False。"""
        engine = make_engine(AmountTypeRule())
        # 8 个 Medium → score=60，无 High
        cols = "\n".join(
            [f"    col_amount_{i} FLOAT COMMENT '金额{i}'," for i in range(1, 9)]
        ).rstrip(",")
        ddl = f"CREATE TABLE t (\n{cols}\n) ENGINE=InnoDB;"
        result = engine.check(ddl)
        assert result.score == 60
        assert result.executable is True
        assert result.passed is False

    def test_invalid_ddl_returns_parse_error(self):
        """无效 DDL（无法解析表名）应返回 PARSE_ERROR 而非抛出异常。

        注意：解析器在 'NOT A CREATE TABLE STATEMENT' 中仍能匹配到
        TABLE 关键字后的 'STATEMENT' 作为表名，因此这里使用确实无法
        解析表名的输入来触发 PARSE_ERROR 路径。
        """
        result = DDLCheckEngine().check("SELECT * FROM foo;")
        assert result.passed is False
        assert result.score == 0
        assert result.executable is False
        assert len(result.issues) == 1
        assert result.issues[0]["rule_id"] == "PARSE_ERROR"

    def test_table_name_and_db_type_filled_in_result(self):
        """结果正确回填 table_name 和 db_type。"""
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            create_time DATETIME COMMENT '创建时间',
            update_time DATETIME COMMENT '更新时间'
        ) ENGINE=InnoDB;"""
        result = DDLCheckEngine().check(ddl, db_type="sqlserver")
        assert result.table_name == "order_detail"
        assert result.db_type == "sqlserver"

    def test_to_dict_contains_required_keys(self):
        """to_dict() 必须包含 passed/score/summary/issues/executable 五个键。"""
        ddl = """CREATE TABLE t (
            id BIGINT COMMENT '主键',
            create_time DATETIME COMMENT '创建时间',
            update_time DATETIME COMMENT '更新时间'
        ) ENGINE=InnoDB;"""
        result = DDLCheckEngine().check(ddl)
        d = result.to_dict()
        for key in ("passed", "score", "summary", "issues", "executable"):
            assert key in d, f"to_dict() 缺少键: {key}"

    def test_to_json_is_valid_json(self):
        """to_json() 返回合法 JSON 字符串。"""
        import json
        ddl = """CREATE TABLE t (
            id BIGINT COMMENT '主键',
            create_time DATETIME COMMENT '创建时间',
            update_time DATETIME COMMENT '更新时间'
        ) ENGINE=InnoDB;"""
        result = DDLCheckEngine().check(ddl)
        parsed = json.loads(result.to_json())
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# 多规则综合测试
# ---------------------------------------------------------------------------

class TestMultiRuleInteraction:

    def test_all_rules_pass_clean_ddl(self):
        """干净 DDL 通过全部规则，issues 为空，score=100。"""
        ddl = """CREATE TABLE dim_product (
            product_id BIGINT NOT NULL COMMENT '产品ID',
            product_name VARCHAR(200) NOT NULL COMMENT '产品名称',
            sale_price DECIMAL(18,2) COMMENT '销售价格',
            create_time DATETIME NOT NULL COMMENT '创建时间',
            update_time DATETIME NOT NULL COMMENT '更新时间',
            PRIMARY KEY (product_id)
        ) ENGINE=InnoDB COMMENT='产品维度表';"""
        result = DDLCheckEngine().check(ddl)
        assert result.issues == []
        assert result.score == 100

    def test_all_five_rules_violated_simultaneously(self):
        """同时触发 5 条规则，issues 列表中包含所有 rule_id。"""
        ddl = """CREATE TABLE BadTable (
            id BIGINT,
            order_amount FLOAT COMMENT '金额'
        ) ENGINE=InnoDB;"""
        result = DDLCheckEngine().check(ddl)
        ids = rule_ids(result.issues)
        assert "RULE_001" in ids, "缺少 RULE_001（表名违规）"
        assert "RULE_002" in ids, "缺少 RULE_002（字段缺注释）"
        assert "RULE_003" in ids, "缺少 RULE_003（金额字段类型）"
        assert "RULE_004" in ids, "缺少 RULE_004（缺 create_time）"
        assert "RULE_005" in ids, "缺少 RULE_005（缺 update_time）"

    def test_each_issue_has_required_keys(self):
        """issues 每一项包含规定的六个字段。"""
        ddl = """CREATE TABLE BadTable (id BIGINT) ENGINE=InnoDB;"""
        result = DDLCheckEngine().check(ddl)
        required_keys = {"rule_id", "risk_level", "object_type", "object_name",
                         "description", "suggestion"}
        for issue in result.issues:
            missing = required_keys - issue.keys()
            assert not missing, f"issue 缺少字段: {missing}"

    def test_custom_rules_only_run_specified_rule(self):
        """传入自定义规则集时，引擎只运行指定规则。"""
        engine = make_engine(CreateTimeRule())
        ddl = """CREATE TABLE BadName (
            id BIGINT,
            order_amount FLOAT
        ) ENGINE=InnoDB;"""
        result = engine.check(ddl)
        ids = rule_ids(result.issues)
        assert ids == ["RULE_004"], f"预期只有 RULE_004，实际: {ids}"

    def test_high_and_medium_combined_score(self):
        """1 High + 1 Medium：score = 100 - 20 - 5 = 75，executable=False（含 High）。"""
        # 缺 update_time(High) + 金额字段 FLOAT(Medium)
        # 同时满足：合规表名、有注释、有 create_time
        ddl = """CREATE TABLE order_detail (
            id BIGINT COMMENT '主键',
            order_amount FLOAT COMMENT '金额',
            create_time DATETIME COMMENT '创建时间'
        ) ENGINE=InnoDB;"""
        result = DDLCheckEngine().check(ddl)
        assert result.score == 75
        assert result.summary["High"] == 1
        assert result.summary["Medium"] == 1
        assert result.executable is False
