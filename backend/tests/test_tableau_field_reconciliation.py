from services.tableau.field_reconciliation import TableauFieldReconciliationService
from services.tableau.models import TableauAsset, TableauConnection, TableauDatasourceField


CATALOG_FIELDS = [
    "订单日期", "数量", "区域", "折扣", "订单 Id", "客户 Id", "城市", "产品名称", "装运模式",
    "区域 (人员)", "退回", "产品 Id", "区域经理", "国家/地区", "邮政编码", "细分", "行 Id",
    "客单价", "利润率", "客户数", "子类别", "发货年份", "发货日期", "销售额", "利润", "客户名称",
    "省/自治区", "类别", "市场", "订单优先级", "制造商", "邮寄方式",
]

QUERYABLE_FIELDS = ["客单价", "利润率", "客户数", "子类别", "发货年份", "发货日期", "销售额", "利润", "客户名称", "省/自治区", "类别"]


def test_reconciliation_marks_catalog_only_and_queryable_fields(db_session):
    conn = TableauConnection(
        name="tableau",
        server_url="https://tableau.local",
        site="mcp",
        token_name="pat",
        token_encrypted="secret",
        owner_id=1,
    )
    db_session.add(conn)
    db_session.flush()
    asset = TableauAsset(
        connection_id=conn.id,
        asset_type="datasource",
        tableau_id="ds-422",
        name="订单+ (示例 - 超市)",
        is_deleted=False,
    )
    db_session.add(asset)
    db_session.flush()
    for field in CATALOG_FIELDS:
        db_session.add(
            TableauDatasourceField(
                asset_id=asset.id,
                datasource_luid="ds-422",
                field_name=field,
                field_caption="",
                data_type="STRING",
                role="dimension",
            )
        )
    db_session.commit()

    result = TableauFieldReconciliationService(db_session).reconcile_asset(
        asset_id=asset.id,
        connection_id=conn.id,
        datasource_luid="ds-422",
        metadata={"fields": [{"name": field} for field in QUERYABLE_FIELDS]},
    )

    assert result.catalog_field_count == 32
    assert result.queryable_field_count == 11
    assert result.catalog_only_count == 21

    rows = {
        row.field_name: row
        for row in db_session.query(TableauDatasourceField).filter(TableauDatasourceField.asset_id == asset.id).all()
    }
    assert rows["订单日期"].mcp_queryable is False
    assert rows["订单日期"].mcp_checked_at is not None
    assert rows["订单日期"].mcp_last_error is None
    assert rows["销售额"].mcp_queryable is True
    assert rows["销售额"].mcp_field_name == "销售额"
