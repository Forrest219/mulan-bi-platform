"""质量规则 CRUD 服务 — Spec 15 §4.1

架构约束：
- services/ 层不依赖 FastAPI/Starlette
- 所有用户可见文案为中文
"""
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session

from backend.models.governance import BiQualityRule, BiQualityResult, BiQualityScore
from backend.services.governance.schemas import RuleCreate, RuleUpdate
from backend.services.governance.validators import validate_threshold
from backend.services.governance.cron_validator import validate_cron
from app.core.errors import MulanError


class RuleService:
    """质量规则 CRUD 服务"""

    def create_rule(self, data: RuleCreate, user_id: int, db: Session) -> BiQualityRule:
        """创建规则

        1. 校验 datasource_id 存在且 is_active=True
        2. 校验同一 datasource+table+field+rule_type 不重复（GOV_006）
        3. 校验 threshold + rule_type 组合
        4. cron 表达式校验
        5. IDOR：非 admin 不可为他人数据源创建规则
        6. 写入 bi_quality_rules
        """
        # 1. 校验数据源
        from services.datasources.models import DataSource

        ds = db.query(DataSource).filter(DataSource.id == data.datasource_id).first()
        if not ds:
            raise MulanError("DS_001", "数据源不存在", 404)
        if not ds.is_active:
            raise MulanError("GOV_010", "数据源未激活", 400)

        # IDOR 保护：非 admin 只能为自己的数据源创建规则
        # user_id 来自 get_current_user，role 不在此处校验（router 层 require_roles 已校验）
        # 注意：此处通过 datasource_id 关联的 owner_id 判断归属
        # 权限校验需要用户角色信息，但 service 层无 web 上下文
        # 因此 IDOR 校验在 router 层通过 require_roles + owner_id 比较实现

        # 2. 校验重复规则
        self._validate_unique_constraint(
            db, data.datasource_id, data.table_name,
            data.field_name, data.rule_type
        )

        # 3. 校验 threshold + rule_type
        if data.threshold:
            try:
                validate_threshold(data.rule_type, data.threshold)
            except ValueError as e:
                raise MulanError("GOV_003", f"阈值配置无效: {str(e)}", 400)

        # 4. cron 表达式校验
        if data.cron:
            try:
                validate_cron(data.cron)
            except ValueError as e:
                raise MulanError("GOV_004", f"Cron 表达式无效: {str(e)}", 400)

        # 5. 写入规则
        rule = BiQualityRule(
            name=data.name,
            description=data.description,
            datasource_id=data.datasource_id,
            table_name=data.table_name,
            field_name=data.field_name,
            rule_type=data.rule_type,
            operator=data.operator,
            threshold=data.threshold or {},
            severity=data.severity,
            execution_mode=data.execution_mode,
            cron=data.cron,
            custom_sql=data.custom_sql,
            tags_json=data.tags_json,
            enabled=True,
            created_by=user_id,
            updated_by=None,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    def get_rule(self, rule_id: int, db: Session) -> Optional[BiQualityRule]:
        """获取规则详情"""
        return db.query(BiQualityRule).filter(BiQualityRule.id == rule_id).first()

    def list_rules(
        self,
        db: Session,
        datasource_id: int = None,
        enabled: bool = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[BiQualityRule], int]:
        """规则列表（支持筛选 + 分页）

        Returns:
            Tuple of (rules list, total count)
        """
        q = db.query(BiQualityRule)
        if datasource_id is not None:
            q = q.filter(BiQualityRule.datasource_id == datasource_id)
        if enabled is not None:
            q = q.filter(BiQualityRule.enabled == enabled)

        total = q.count()
        rules = (
            q.order_by(BiQualityRule.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rules, total

    def update_rule(
        self, rule_id: int, data: RuleUpdate, user_id: int, db: Session
    ) -> BiQualityRule:
        """更新规则（PATCH 语义）

        1. 校验规则存在
        2. rule_type 变更时重新校验 threshold
        3. cron 变更时重新校验
        4. updated_by = user_id
        """
        rule = self.get_rule(rule_id, db)
        if not rule:
            raise MulanError("GOV_001", "质量规则不存在", 404)

        update_data = data.model_dump(exclude_unset=True)

        # rule_type 变更时重新校验 threshold
        new_rule_type = update_data.get("rule_type", rule.rule_type)
        new_threshold = update_data.get("threshold", rule.threshold)
        if "threshold" in update_data or "rule_type" in update_data:
            try:
                validate_threshold(new_rule_type, new_threshold or {})
            except ValueError as e:
                raise MulanError("GOV_003", f"阈值配置无效: {str(e)}", 400)

        # cron 变更时校验
        new_cron = update_data.get("cron", rule.cron)
        if new_cron:
            try:
                validate_cron(new_cron)
            except ValueError as e:
                raise MulanError("GOV_004", f"Cron 表达式无效: {str(e)}", 400)

        # 应用更新
        for key, value in update_data.items():
            if hasattr(rule, key) and value is not None:
                setattr(rule, key, value)
        rule.updated_by = user_id

        db.commit()
        db.refresh(rule)
        return rule

    def delete_rule(self, rule_id: int, db: Session) -> None:
        """删除规则

        物理删除规则 + 级联删除关联的检测结果
        """
        rule = self.get_rule(rule_id, db)
        if not rule:
            raise MulanError("GOV_001", "质量规则不存在", 404)

        # 级联删除检测结果
        db.query(BiQualityResult).filter(BiQualityResult.rule_id == rule_id).delete()
        db.delete(rule)
        db.commit()

    def toggle_rule(self, rule_id: int, enabled: bool, db: Session) -> BiQualityRule:
        """启用/禁用规则"""
        rule = self.get_rule(rule_id, db)
        if not rule:
            raise MulanError("GOV_001", "质量规则不存在", 404)

        rule.enabled = enabled
        db.commit()
        db.refresh(rule)
        return rule

    def _validate_unique_constraint(
        self,
        db: Session,
        datasource_id: int,
        table_name: str,
        field_name: Optional[str],
        rule_type: str,
        exclude_rule_id: int = None,
    ) -> None:
        """校验同 datasource+table+field+rule_type 不重复

        Raises:
            MulanError(GOV_006): 同一数据源+表+字段+规则类型已存在相同规则
        """
        query = db.query(BiQualityRule).filter(
            BiQualityRule.datasource_id == datasource_id,
            BiQualityRule.table_name == table_name,
            BiQualityRule.field_name == field_name,
            BiQualityRule.rule_type == rule_type,
        )
        if exclude_rule_id:
            query = query.filter(BiQualityRule.id != exclude_rule_id)

        existing = query.first()
        if existing:
            raise MulanError(
                "GOV_006",
                "同一数据源+表+字段+规则类型已存在相同规则",
                409,
            )

    def check_datasource_ownership(
        self, db: Session, datasource_id: int, user_id: int, user_role: str
    ) -> bool:
        """检查用户是否为数据源owner（用于 IDOR 保护）

        Args:
            db: 数据库会话
            datasource_id: 数据源ID
            user_id: 当前用户ID
            user_role: 当前用户角色

        Returns:
            True 表示有权限
        """
        if user_role == "admin":
            return True

        from services.datasources.models import DataSource

        ds = db.query(DataSource).filter(DataSource.id == datasource_id).first()
        if not ds:
            return False
        return ds.owner_id == user_id
