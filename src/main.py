"""Mulan - DDL 规范管理平台 Web 界面"""
import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ddl_checker import DDLSanner, DDLScanResult
from src.ddl_generator import DDLGenerator, TableDefinition, ColumnDefinition, IndexDefinition
from src.ddl_generator.templates import DDLTemplateGenerator, TableTemplate
from src.logs import logger

# 页面配置
st.set_page_config(
    page_title="Mulan - DDL 规范管理平台",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义样式
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #2E7D32;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f5f5f5;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
    }
    .error-text { color: #d32f2f; font-weight: bold; }
    .warning-text { color: #f57c00; font-weight: bold; }
    .info-text { color: #1976d2; }
    .success-text { color: #2e7d32; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """初始化会话状态"""
    if "scanner" not in st.session_state:
        st.session_state.scanner = None
    if "last_report" not in st.session_state:
        st.session_state.last_report = None
    if "db_config" not in st.session_state:
        st.session_state.db_config = {}


def render_header():
    """渲染页面头部"""
    st.markdown('<p class="main-header">Mulan - DDL 规范管理平台</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">BI 团队 DDL 规范检查与生成工具</p>', unsafe_allow_html=True)


def render_sidebar():
    """渲染侧边栏"""
    st.sidebar.title("功能导航")
    st.sidebar.markdown("---")

    # 使用 session_state 跟踪当前页面
    if "current_page" not in st.session_state:
        st.session_state.current_page = "首页"

    if st.sidebar.button("🏠 首页", use_container_width=True):
        st.session_state.current_page = "首页"
        st.rerun()
    if st.sidebar.button("🔍 DDL 规范检查", use_container_width=True):
        st.session_state.current_page = "DDL 规范检查"
        st.rerun()
    if st.sidebar.button("⚙️ DDL 生成器", use_container_width=True):
        st.session_state.current_page = "DDL 生成器"
        st.rerun()
    if st.sidebar.button("📋 报告查看", use_container_width=True):
        st.session_state.current_page = "报告查看"
        st.rerun()
    if st.sidebar.button("📊 扫描日志", use_container_width=True):
        st.session_state.current_page = "扫描日志"
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.info("""
    **项目信息**
    - 项目名称：Mulan
    - 开始日期：2026-03-24
    - 版本：v1.0.0
    """)

    return st.session_state.current_page


def render_home_page():
    """渲染首页"""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("功能模块", "2 个", "DDL 检查 / DDL 生成")
    with col2:
        st.metric("规则配置", "已就绪", "config/rules.yaml")
    with col3:
        st.metric("数据库连接", "待配置", "请在检查页面设置")
    with col4:
        st.metric("项目周期", "进行中", "2026-03-24 启动")

    st.markdown("---")

    st.subheader("功能说明")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        ### 🔍 DDL 规范检查
        对现有数据库的表单做监控、审查、报警

        **功能特性：**
        - 连接 MySQL / PostgreSQL 数据库
        - 自动扫描所有表结构
        - 按照规则库检查违规项
        - 生成 HTML/JSON 格式报告
        - 支持定时监控和报警

        **检查项目：**
        - 表命名规范
        - 字段命名规范
        - 数据类型规范
        - 主键/索引规范
        - 注释规范
        - 时间戳字段规范
        """)

    with col2:
        st.markdown("""
        ### ⚙️ DDL 生成器
        通过配置界面生成符合规范的建表语句

        **功能特性：**
        - 可视化配置表结构
        - 预置常用表模板
        - 自动遵循命名规范
        - 支持批量生成
        - 一键复制到剪贴板

        **支持表类型：**
        - 维度表 (dim_)
        - 事实表 (fact_)
        - ODS 层表 (ods_)
        - DWD 层表 (dwd_)
        """)


def render_checker_page():
    """渲染 DDL 规范检查页面"""
    st.subheader("🔍 DDL 规范检查")

    # 数据库配置
    with st.expander("数据库配置", expanded=st.session_state.scanner is None):
        col1, col2, col3 = st.columns(3)

        with col1:
            db_type = st.selectbox("数据库类型", ["mysql", "postgresql", "sqlite"], index=0)
        with col2:
            host = st.text_input("主机地址", value="localhost" if db_type != "sqlite" else "")
        with col3:
            port = st.number_input("端口", value=3306 if db_type == "mysql" else 5432)

        col1, col2, col3 = st.columns(3)
        with col1:
            user = st.text_input("用户名", value="root")
        with col2:
            password = st.text_input("密码", type="password")
        with col3:
            database = st.text_input("数据库名", value="test_db")

        if st.button("连接数据库", type="primary"):
            db_config = {
                "db_type": db_type,
                "host": host,
                "port": int(port),
                "user": user,
                "password": password,
                "database": database
            }
            st.session_state.db_config = db_config
            st.session_state.scanner = DDLSanner()

            if st.session_state.scanner.connect_database(db_config):
                st.success("数据库连接成功！")
            else:
                st.error("数据库连接失败，请检查配置。")

    # 检查操作
    if st.session_state.scanner and st.session_state.scanner.connector:
        st.success(f"已连接数据库: {st.session_state.db_config.get('database')}")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("🔍 扫描所有表", type="primary", use_container_width=True):
                with st.spinner("正在扫描..."):
                    result = st.session_state.scanner.scan_all_tables()
                    if result.success:
                        st.session_state.last_report = result.report
                        st.success("扫描完成！")
                    else:
                        st.error(f"扫描失败: {result.error}")

        with col2:
            selected_table = st.selectbox("选择表", ["全部"] + st.session_state.scanner.connector.get_table_names())
            if st.button("🔍 扫描选中表", type="secondary", use_container_width=True):
                if selected_table != "全部":
                    with st.spinner(f"正在扫描表 {selected_table}..."):
                        result = st.session_state.scanner.scan_table(selected_table)
                        if result.success:
                            st.session_state.last_report = result.report
                            st.success("扫描完成！")
                        else:
                            st.error(f"扫描失败: {result.error}")

        # SQL 检查
        st.markdown("---")
        st.subheader("SQL 语句检查")
        sql_input = st.text_area("输入 CREATE TABLE SQL 语句", height=150, placeholder="CREATE TABLE ...")

        if st.button("🔍 检查 SQL", type="secondary"):
            if sql_input.strip():
                with st.spinner("正在检查..."):
                    result = st.session_state.scanner.scan_sql(sql_input)
                    if result.success:
                        st.session_state.last_report = result.report
                        st.success("检查完成！")
                    else:
                        st.error(f"检查失败: {result.error}")
            else:
                st.warning("请输入 SQL 语句")

    else:
        st.info("请先配置并连接数据库")

    # 显示检查结果
    if st.session_state.last_report:
        st.markdown("---")
        render_report(st.session_state.last_report)


def render_report(report):
    """渲染报告"""
    st.subheader("📊 检查报告")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("检查表数", report.total_tables)
    col2.metric("错误", report.error_count, delta_color="inverse")
    col3.metric("警告", report.warning_count, delta_color="off")
    col4.metric("提示", report.info_count, delta_color="off")

    if report.total_violations == 0:
        st.success("🎉 所有检查项均通过规范！")
    else:
        st.warning(f"发现 {report.total_violations} 个违规项，请查看详情")

    # 显示违规详情
    for table_name, violations in report.table_results.items():
        if violations:
            with st.expander(f"📋 {table_name} ({len(violations)} 个违规)", expanded=False):
                for v in violations:
                    level_icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[v["level"]]
                    level_color = {"error": "error", "warning": "warning", "info": "info"}[v["level"]]

                    col1, col2 = st.columns([1, 4])
                    with col1:
                        st.markdown(f"**{level_icon} {v['level'].upper()}**")
                    with col2:
                        st.markdown(f"**{v['message']}**")
                        if v["column_name"]:
                            st.caption(f"列: {v['column_name']}")
                        if v["suggestion"]:
                            st.info(f"💡 建议: {v['suggestion']}")
                    st.markdown("---")

    # 导出报告
    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("📥 导出 HTML 报告"):
            output_path = "/tmp/ddl_check_report.html"
            st.session_state.scanner.export_report(report, output_path, "html")
            st.success(f"报告已导出到: {output_path}")
            with open(output_path, "r") as f:
                st.download_button("下载报告", f.read(), file_name="ddl_check_report.html", mime="text/html")

    with col2:
        if st.button("📥 导出 JSON 报告"):
            output_path = "/tmp/ddl_check_report.json"
            st.session_state.scanner.export_report(report, output_path, "json")
            st.success(f"报告已导出到: {output_path}")


def render_generator_page():
    """渲染 DDL 生成器页面"""
    st.subheader("⚙️ DDL 生成器")

    tab1, tab2 = st.tabs(["📝 手动创建", "📦 使用模板"])

    with tab1:
        render_manual_generator()

    with tab2:
        render_template_generator()


def render_manual_generator():
    """手动创建 DDL"""
    generator = DDLGenerator(str(Path(__file__).parent.parent / "config" / "rules.yaml"))

    # 表基本信息
    st.markdown("### 表信息")
    col1, col2 = st.columns(2)
    with col1:
        table_name = st.text_input("表名", placeholder="dim_user_info")
    with col2:
        table_comment = st.text_input("表注释", placeholder="用户维度表")

    if table_name:
        valid, msg = generator.validate_table_name(table_name)
        if valid:
            st.markdown(f"<span class='success-text'>✅ {msg}</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"<span class='error-text'>❌ {msg}</span>", unsafe_allow_html=True)

    # 列定义
    st.markdown("### 列定义")
    columns = []

    with st.expander("添加列", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            col_name = st.text_input("列名", key="col_name_input", placeholder="user_name")
        with col2:
            col_type = st.selectbox("数据类型", ["BIGINT", "DECIMAL", "VARCHAR", "TEXT", "DATETIME", "DATE", "BOOLEAN", "INT", "TINYINT"], key="col_type_input")
        with col3:
            col_length = st.number_input("长度", value=0, min_value=0, key="col_length_input")

        col1, col2, col3 = st.columns(3)
        with col1:
            col_nullable = st.checkbox("允许为空", value=True, key="col_nullable_input")
        with col2:
            col_default = st.text_input("默认值", key="col_default_input")
        with col3:
            col_is_pk = st.checkbox("主键", key="col_pk_input")

        col_comment = st.text_input("列注释", key="col_comment_input")

        if st.button("添加列"):
            if col_name:
                valid, msg = generator.validate_column_name(col_name)
                if valid:
                    columns.append({
                        "name": col_name,
                        "data_type": col_type,
                        "length": col_length if col_length > 0 else None,
                        "nullable": col_nullable,
                        "default": col_default if col_default else None,
                        "is_primary_key": col_is_pk,
                        "comment": col_comment
                    })
                    st.success(f"已添加列: {col_name}")
                else:
                    st.error(msg)

    # 显示已添加的列
    if "columns" not in st.session_state:
        st.session_state.columns = []

    if st.button("确认添加"):
        if col_name:
            valid, _ = generator.validate_column_name(col_name)
            if valid:
                st.session_state.columns.append({
                    "name": col_name,
                    "data_type": col_type,
                    "length": col_length if col_length > 0 else None,
                    "nullable": col_nullable,
                    "default": col_default if col_default else None,
                    "is_primary_key": col_is_pk,
                    "comment": col_comment
                })

    if st.session_state.columns:
        st.markdown("#### 已添加的列")
        for i, col in enumerate(st.session_state.columns):
            col_display = f"{col['name']} ({col['data_type']}"
            if col['length']:
                col_display += f", 长度={col['length']}"
            col_display += ")"
            if col['is_primary_key']:
                col_display += " 🔑"
            st.markdown(f"- {col_display}")

    # 生成 DDL
    st.markdown("---")
    if st.button("⚡ 生成 DDL", type="primary", use_container_width=True):
        if table_name and st.session_state.columns:
            table = TableDefinition(
                table_name=table_name,
                comment=table_comment
            )

            for col in st.session_state.columns:
                table.add_column(ColumnDefinition(
                    name=col["name"],
                    data_type=col["data_type"],
                    length=col.get("length"),
                    nullable=col.get("nullable", True),
                    default=col.get("default"),
                    comment=col.get("comment", ""),
                    is_primary_key=col.get("is_primary_key", False)
                ))

            ddl = generator.generate_create_table(table)
            st.session_state.generated_ddl = ddl
        else:
            st.warning("请输入表名并添加至少一列")

    # 显示生成的 DDL
    if "generated_ddl" in st.session_state:
        st.markdown("#### 生成的 DDL")
        st.code(st.session_state.generated_ddl, language="sql")

        if st.button("📋 复制到剪贴板"):
            st.success("已复制！")


def render_template_generator():
    """使用模板生成 DDL"""
    template_generator = DDLTemplateGenerator(str(Path(__file__).parent.parent / "config" / "rules.yaml"))

    template_type = st.selectbox("选择模板", ["维度表 (dim_)", "事实表 (fact_)", "ODS 层表 (ods_)", "DWD 层表 (dwd_)"])

    col1, col2 = st.columns(2)
    with col1:
        table_name = st.text_input("表名", placeholder="dim_user")
    with col2:
        table_comment = st.text_input("表注释", placeholder="用户维度表")

    st.markdown("---")
    st.markdown("#### 字段配置")

    if template_type.startswith("维度表"):
        st.info("维度表适用场景：缓慢变化维，如用户表、商品表、地域表等")

        num_keys = st.number_input("业务主键数量", value=1, min_value=1, max_value=10)
        business_keys = []
        for i in range(num_keys):
            key_name = st.text_input(f"业务主键 {i+1}", value=f"user_id" if i == 0 else "")
            business_keys.append(key_name)

        num_attrs = st.number_input("属性字段数量", value=3, min_value=0, max_value=50)
        attributes = []
        for i in range(num_attrs):
            col1, col2, col3 = st.columns(3)
            with col1:
                attr_name = st.text_input(f"属性名 {i+1}", value=["user_name", "user_email", "user_type"][i] if i < 3 else "")
            with col2:
                attr_type = st.selectbox(f"类型 {i+1}", ["VARCHAR", "BIGINT", "DECIMAL", "DATETIME", "DATE", "TEXT"], index=0)
            with col3:
                attr_len = st.number_input(f"长度 {i+1}", value=64, min_value=1)
            attr_comment = st.text_input(f"注释 {i+1}")
            if attr_name:
                attributes.append({
                    "name": attr_name,
                    "data_type": attr_type,
                    "length": attr_len,
                    "comment": attr_comment
                })

        if st.button("⚡ 生成维度表 DDL", type="primary"):
            if table_name and business_keys and attributes:
                ddl = template_generator.create_dim_table(table_name, business_keys, attributes)
                st.session_state.generated_ddl = ddl

    elif template_type.startswith("事实表"):
        st.info("事实表适用场景：业务过程事实记录，如订单表、支付表、访问日志表等")

        num_dims = st.number_input("维度外键数量", value=2, min_value=1, max_value=10)
        dimension_keys = []
        for i in range(num_dims):
            key_name = st.text_input(f"维度外键 {i+1}", value=f"user_id" if i == 0 else f"product_id" if i == 1 else "")
            dimension_keys.append(key_name)

        num_facts = st.number_input("事实字段数量", value=3, min_value=0, max_value=50)
        facts = []
        for i in range(num_facts):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                fact_name = st.text_input(f"事实名 {i+1}", value=["order_amount", "order_count", "pay_amount"][i] if i < 3 else "")
            with col2:
                fact_type = st.selectbox(f"类型 {i+1}", ["DECIMAL", "BIGINT", "INT"], index=0)
            with col3:
                fact_len = st.number_input(f"长度 {i+1}", value=18, min_value=1)
            with col4:
                fact_dec = st.number_input(f"小数位 {i+1}", value=4, min_value=0)
            fact_comment = st.text_input(f"注释 {i+1}")
            if fact_name:
                facts.append({
                    "name": fact_name,
                    "data_type": fact_type,
                    "length": fact_len,
                    "decimal_length": fact_dec,
                    "comment": fact_comment
                })

        if st.button("⚡ 生成事实表 DDL", type="primary"):
            if table_name and dimension_keys and facts:
                ddl = template_generator.create_fact_table(table_name, facts, dimension_keys)
                st.session_state.generated_ddl = ddl

    elif template_type.startswith("ODS"):
        st.info("ODS 层表适用场景：原始数据层，暂存源系统抽取数据")

        num_cols = st.number_input("源表字段数量", value=5, min_value=0, max_value=100)
        source_columns = []
        for i in range(num_cols):
            col1, col2, col3 = st.columns(3)
            with col1:
                col_name = st.text_input(f"字段名 {i+1}", value=f"col_{i+1}")
            with col2:
                col_type = st.selectbox(f"类型 {i+1}", ["VARCHAR", "BIGINT", "DECIMAL", "DATETIME", "DATE", "TEXT", "INT"], index=0, key=f"ods_type_{i}")
            with col3:
                col_len = st.number_input(f"长度 {i+1}", value=255, min_value=1, key=f"ods_len_{i}")
            col_comment = st.text_input(f"注释 {i+1}", key=f"ods_comment_{i}")
            if col_name:
                source_columns.append({
                    "name": col_name,
                    "data_type": col_type,
                    "length": col_len,
                    "comment": col_comment
                })

        if st.button("⚡ 生成 ODS 表 DDL", type="primary"):
            if table_name and source_columns:
                ddl = template_generator.create_ods_table(table_name, source_columns)
                st.session_state.generated_ddl = ddl

    elif template_type.startswith("DWD"):
        st.info("DWD 层表适用场景：明细宽表层，整合多个维度的事实表")

        num_keys = st.number_input("业务主键数量", value=1, min_value=1, max_value=5)
        business_keys = []
        for i in range(num_keys):
            key_name = st.text_input(f"业务主键 {i+1}", value=f"order_id" if i == 0 else "")
            business_keys.append(key_name)

        num_dims = st.number_input("维度外键数量", value=2, min_value=0, max_value=10)
        dimension_refs = []
        for i in range(num_dims):
            dim_key = st.text_input(f"维度外键 {i+1}", value=f"user_id" if i == 0 else f"product_id" if i == 1 else "")
            if dim_key:
                dimension_refs.append(dim_key)

        num_attrs = st.number_input("属性字段数量", value=5, min_value=0, max_value=50)
        attributes = []
        for i in range(num_attrs):
            col1, col2, col3 = st.columns(3)
            with col1:
                attr_name = st.text_input(f"属性名 {i+1}", value=f"attr_{i+1}")
            with col2:
                attr_type = st.selectbox(f"类型 {i+1}", ["VARCHAR", "BIGINT", "DECIMAL", "DATETIME", "DATE", "TEXT"], index=0, key=f"dwd_type_{i}")
            with col3:
                attr_len = st.number_input(f"长度 {i+1}", value=64, min_value=1, key=f"dwd_len_{i}")
            attr_comment = st.text_input(f"注释 {i+1}", key=f"dwd_comment_{i}")
            if attr_name:
                attributes.append({
                    "name": attr_name,
                    "data_type": attr_type,
                    "length": attr_len,
                    "comment": attr_comment
                })

        if st.button("⚡ 生成 DWD 表 DDL", type="primary"):
            if table_name and business_keys:
                ddl = template_generator.create_dwd_table(table_name, business_keys, attributes, dimension_refs)
                st.session_state.generated_ddl = ddl

    # 显示生成的 DDL
    if "generated_ddl" in st.session_state:
        st.markdown("---")
        st.markdown("#### 生成的 DDL")
        st.code(st.session_state.generated_ddl, language="sql")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📋 复制到剪贴板"):
                st.success("已复制！")
        with col2:
            if st.button("🗑️ 清空"):
                st.session_state.pop("generated_ddl", None)
                st.rerun()


def render_report_page():
    """渲染报告查看页面"""
    st.subheader("📋 历史报告")

    st.info("报告查看功能开发中...")
    st.markdown("""
    **功能说明：**
    - 查看历史检查报告
    - 对比不同时间点的检查结果
    - 追踪违规项的修复状态
    """)


def render_logs_page():
    """渲染扫描日志页面"""
    st.subheader("📊 扫描日志")

    # 获取统计数据
    stats = logger.get_statistics()

    col1, col2, col3 = st.columns(3)
    col1.metric("总扫描次数", stats.get("total_scans", 0))
    col2.metric("总扫描表数", stats.get("total_tables", 0))
    col3.metric("总发现违规", stats.get("total_violations", 0))

    st.markdown("---")

    # 扫描历史
    st.subheader("📋 扫描历史")

    # 筛选器
    col1, col2 = st.columns(2)
    with col1:
        filter_db = st.selectbox("筛选数据库", ["全部"] + ["bi_read", "bidm", "ccw_bidw", "ccw_biods", "mj_test", "sql_playground"])
    with col2:
        filter_limit = st.slider("显示条数", 10, 200, 50)

    # 获取日志
    db_filter = None if filter_db == "全部" else filter_db
    scan_logs = logger.get_scan_history(limit=filter_limit, database_name=db_filter)

    if scan_logs:
        # 表格展示
        for log in scan_logs:
            with st.expander(f"🔍 {log['scan_time']} | {log['database_name']} | {log['table_count']} 表 | {log['total_violations']} 违规", expanded=False):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**状态:** {'✅ 成功' if log['status'] == 'completed' else '❌ 失败'}")
                    st.write(f"**数据库:** {log['database_name']}")
                    st.write(f"**DB类型:** {log['db_type']}")
                with col2:
                    st.write(f"**表数量:** {log['table_count']}")
                    st.write(f"**耗时:** {log['duration_seconds']} 秒")
                with col3:
                    st.write(f"❌ 错误: {log['error_count']}")
                    st.write(f"⚠️ 警告: {log['warning_count']}")
                    st.write(f"ℹ️ 提示: {log['info_count']}")

                if log.get('error_message'):
                    st.error(f"错误信息: {log['error_message']}")
    else:
        st.info("暂无扫描记录，请先进行扫描操作")

    # 规则变更日志
    st.markdown("---")
    st.subheader("⚙️ 规则变更历史")

    rule_logs = logger.get_rule_change_history(limit=20)
    if rule_logs:
        for log in rule_logs:
            with st.expander(f"📝 {log['change_time']} | {log['rule_section']} | {log['change_type']}", expanded=False):
                st.write(f"**操作人:** {log['operator']}")
                st.write(f"**变更类型:** {log['change_type']}")
                st.write(f"**描述:** {log['description'] or '无'}")
    else:
        st.info("暂无规则变更记录")

    # 操作日志
    st.markdown("---")
    st.subheader("📜 操作日志")

    op_logs = logger.get_operation_history(limit=30)
    if op_logs:
        for log in op_logs:
            status_icon = "✅" if log['status'] == 'success' else "❌"
            with st.expander(f"{status_icon} {log['op_time']} | {log['operation_type']} | {log['target'] or ''}", expanded=False):
                st.write(f"**操作人:** {log['operator']}")
                st.write(f"**操作类型:** {log['operation_type']}")
                st.write(f"**目标:** {log['target'] or '无'}")
                st.write(f"**状态:** {log['status']}")
    else:
        st.info("暂无操作记录")


def main():
    """主函数"""
    init_session_state()
    render_header()
    page = render_sidebar()

    if page == "首页":
        render_home_page()
    elif page == "DDL 规范检查":
        render_checker_page()
    elif page == "DDL 生成器":
        render_generator_page()
    elif page == "报告查看":
        render_report_page()
    elif page == "扫描日志":
        render_logs_page()


if __name__ == "__main__":
    main()
