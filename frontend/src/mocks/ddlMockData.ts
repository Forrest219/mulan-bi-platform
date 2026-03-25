export type Severity = 'HIGH' | 'MEDIUM' | 'LOW';

export interface ValidationIssue {
  ruleId: string;
  severity: Severity;
  target: string;
  message: string;
  suggestion: string;
}

export interface ValidationResult {
  score: number;
  high: number;
  medium: number;
  low: number;
  allowed: boolean;
  issues: ValidationIssue[];
}

export const mockValidationResult: ValidationResult = {
  score: 58,
  high: 2,
  medium: 3,
  low: 4,
  allowed: false,
  issues: [
    {
      ruleId: 'DDL-001',
      severity: 'HIGH',
      target: 'TABLE: order_detail',
      message: '表缺少主键约束（PRIMARY KEY）',
      suggestion: '为表添加 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY',
    },
    {
      ruleId: 'DDL-002',
      severity: 'HIGH',
      target: 'COLUMN: user_id',
      message: '外键字段 user_id 未定义索引，将导致全表扫描',
      suggestion: '添加 INDEX idx_user_id (user_id)',
    },
    {
      ruleId: 'DDL-010',
      severity: 'MEDIUM',
      target: 'COLUMN: OrderStatus',
      message: '字段命名不符合 snake_case 规范（发现 CamelCase）',
      suggestion: '将 OrderStatus 重命名为 order_status',
    },
    {
      ruleId: 'DDL-011',
      severity: 'MEDIUM',
      target: 'COLUMN: remark',
      message: 'TEXT 类型字段 remark 未限制最大长度，建议使用 VARCHAR(500)',
      suggestion: '将 TEXT 改为 VARCHAR(500) 并添加默认值',
    },
    {
      ruleId: 'DDL-012',
      severity: 'MEDIUM',
      target: 'TABLE: order_detail',
      message: '缺少 created_at / updated_at 审计时间字段',
      suggestion: '添加 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP 和 updated_at DATETIME',
    },
    {
      ruleId: 'DDL-020',
      severity: 'LOW',
      target: 'COLUMN: price',
      message: '金额字段 price 使用 FLOAT 类型，存在精度丢失风险',
      suggestion: '将 FLOAT 替换为 DECIMAL(15,4)',
    },
    {
      ruleId: 'DDL-021',
      severity: 'LOW',
      target: 'COLUMN: status',
      message: '字段 status 缺少 COMMENT 注释说明',
      suggestion: "添加 COMMENT '订单状态: 0-待支付 1-已支付 2-已取消'",
    },
    {
      ruleId: 'DDL-022',
      severity: 'LOW',
      target: 'COLUMN: created_by',
      message: '字段 created_by 未设置默认值',
      suggestion: "添加 DEFAULT ''",
    },
    {
      ruleId: 'DDL-023',
      severity: 'LOW',
      target: 'TABLE: order_detail',
      message: '表缺少 TABLE COMMENT 注释',
      suggestion: "在建表语句末尾添加 COMMENT='订单明细表'",
    },
  ],
};

export const sampleSql = `CREATE TABLE order_detail (
  order_id      BIGINT NOT NULL,
  user_id       BIGINT NOT NULL,
  product_id    BIGINT NOT NULL,
  OrderStatus   TINYINT DEFAULT 0,
  price         FLOAT,
  quantity      INT NOT NULL,
  remark        TEXT,
  created_by    VARCHAR(64),
  status        TINYINT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;`;
