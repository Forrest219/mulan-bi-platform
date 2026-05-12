"""
test_intent_routing — is_direct_query 黑名单/白名单路由测试

测试目标：
- 复杂问数（黑名单）→ is_direct_query == False → 走 ReAct
- 简单问数（白名单）→ is_direct_query == True  → 走快通
- 组合场景：同时命中黑+白时，黑名单优先
"""
import pytest

from services.data_agent.intent.keyword_match import is_direct_query


# ─── 黑名单：必须返回 False ──────────────────────────────────────────────

class TestBlacklistComplex:
    """命中黑名单 → 走完整 ReAct"""

    @pytest.mark.parametrize("question", [
        # 因果/归因
        "为什么Q1销售额下降了",
        "利润下滑的原因是什么",
        "导致本月收入减少的因素",
        "用户流失影响了哪些指标",
        "为何去年同期表现更好",
        # 分析/解读
        "分析一下各区域的销售表现",
        "解读这份报表的波动原因",
        "拆解收入增长的结构",
        "对本月数据做一下洞察",
        # 对比/差异
        "对比华东和华北的市场份额",
        "今年和去年的收入差异",
        "比较不同产品的利润率",
        "华东区和华西区的区别在哪里",
        # 预测/建议
        "预测下季度的销量",
        "如何提升转化率",
        "给一些优化建议",
        "改善运营效率的方法",
        "提升客单价要怎么操作",
        # 异常/发现问题
        "数据异常的原因",
        "本月GMV下滑问题",
        "发现订单量下降",
        # 报表生成
        "生成一张销售报表",
        "生成本月利润报告",
        "做个报表看看",
        "输出一张数据报表",
        # 组合短语
        "分析一下原因是什么",
        "如何改善当前状况",
        "相关性分析怎么做",
        "找出关联影响因素",
    ])
    def test_blacklist_returns_false(self, question: str):
        assert is_direct_query(question) is False, \
            f"黑名单问题应返回 False，实际返回 True：{question}"


# ─── 白名单：必须返回 True ───────────────────────────────────────────────

class TestWhitelistSimple:
    """命中白名单 → 可走快通"""

    @pytest.mark.parametrize("question", [
        # 时间区间
        "这些渠道过去几年的利润情况如何？",
        "哪些渠道过去几年的利润一直在涨？",
        "过去3年的销售额",
        "过去12个月的销售数据",
        "2024年的总收入",
        "今年Q1订单数",
        "去年各区域的销量",
        # 群体查询
        "每个产品的销售额",
        "各类别的订单数量",
        "各区域的收入分布",
        "各城市的客户数量",
        # 指标查询
        "销售额是多少",
        "有多少笔订单",
        "总收入统计",
        # 趋势组合
        "销售额走势如何",
        "利润变化趋势",
        "收入趋势分析",
        # deterministic TopN + 占比
        "按销售额排，2024 年 Top10 大客户是谁？分别占当年销售额的比例是多少？",
        # deterministic customer churn
        "哪些 2021 年的老客户流失了（定义 2021 年有订单，但最近一年没有订单）？",
    ])
    def test_whitelist_returns_true(self, question: str):
        assert is_direct_query(question) is True, \
            f"白名单问题应返回 True，实际返回 False：{question}"


# ─── 排除项：白名单里有但设计排除的 ─────────────────────────────────────

class TestExcludedFromWhitelist:
    """top/排名、占比、同比/环比 按设计排除，不走快通"""

    @pytest.mark.parametrize("question", [
        # top/排名
        "销售额前10的产品",
        "top5客户",
        "排名最靠前的区域",
        # 占比（VizQL 歧义）
        "各类别销售额占比",
        "市场占有率",
        "利润百分比",
        # 同比/环比（需二次计算）
        "销售额同比增长",
        "环比上月变化",
        # schema / metadata questions
        "请查看 Tableau 数据资产 bidm_ai_metric_summary_mth-月度指标汇总表 有哪些字段？",
        "customers-客户维度表有哪些字段？",
        "查看订单表的表结构",
        "这个数据资产的 schema 是什么？",
    ])
    def test_excluded_returns_false(self, question: str):
        assert is_direct_query(question) is False, \
            f"排除项应返回 False（不走快通），实际返回 True：{question}"


# ─── 边界/未知：应返回 False ───────────────────────────────────────────

class TestUnknown:
    """无法识别 → 返回 False（保守策略，走 ReAct）"""

    @pytest.mark.parametrize("question", [
        "你好",
        "今天天气怎么样",
        "帮我查一下",
        "随便看看数据",
        "",
    ])
    def test_unknown_returns_false(self, question: str):
        assert is_direct_query(question) is False, \
            f"未知问题应返回 False，实际返回 True：{question}"


# ─── 组合场景：黑名单优先于白名单 ────────────────────────────────────────

class TestBlacklistWins:
    """同时命中黑+白，黑名单优先"""

    def test_趋势但带原因(self):
        # 白名单匹配"趋势"，但黑名单匹配"分析"
        assert is_direct_query("分析一下销售额的趋势变化") is False

    def test_同比但带分析(self):
        # 白名单匹配"同比"，但黑名单匹配"为什么"
        assert is_direct_query("为什么同比下降了") is False

    def test_占比但带原因(self):
        # 白名单匹配"占比"，但黑名单匹配"原因"
        assert is_direct_query("各类别占比变化的原因") is False
