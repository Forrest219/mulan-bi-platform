export type RuleLevel = 'HIGH' | 'MEDIUM' | 'LOW';
export type RuleStatus = 'enabled' | 'disabled';
export type RuleCategory = 'Naming' | 'Structure' | 'Type' | 'Index' | 'Audit';

export interface ValidationRule {
  id: string;
  name: string;
  category: RuleCategory;
  level: RuleLevel;
  status: RuleStatus;
  description: string;
  dbType: 'MySQL' | 'SQL Server' | 'All';
  builtIn: boolean;
}

export const mockRules: ValidationRule[] = [
  { id: 'DDL-001', name: '主键缺失检测', category: 'Structure', level: 'HIGH', status: 'enabled', description: '检查表是否定义了 PRIMARY KEY 约束', dbType: 'All', builtIn: true },
  { id: 'DDL-002', name: '外键索引检测', category: 'Index', level: 'HIGH', status: 'enabled', description: '检查外键字段是否创建对应索引', dbType: 'All', builtIn: true },
  { id: 'DDL-003', name: '自增主键类型', category: 'Type', level: 'HIGH', status: 'enabled', description: '自增主键必须使用 BIGINT 类型', dbType: 'MySQL', builtIn: true },
  { id: 'DDL-010', name: '字段命名规范 (snake_case)', category: 'Naming', level: 'MEDIUM', status: 'enabled', description: '字段名必须使用 snake_case 小写下划线格式', dbType: 'All', builtIn: true },
  { id: 'DDL-011', name: 'TEXT 类型限制', category: 'Type', level: 'MEDIUM', status: 'enabled', description: '不允许使用无长度限制的 TEXT 字段', dbType: 'All', builtIn: true },
  { id: 'DDL-012', name: '审计字段检查', category: 'Audit', level: 'MEDIUM', status: 'enabled', description: '表必须包含 created_at 和 updated_at 字段', dbType: 'All', builtIn: true },
  { id: 'DDL-013', name: '表名前缀规范', category: 'Naming', level: 'MEDIUM', status: 'disabled', description: '表名必须以业务域前缀开头（如 ord_, usr_）', dbType: 'All', builtIn: false },
  { id: 'DDL-020', name: '金额字段精度', category: 'Type', level: 'LOW', status: 'enabled', description: '金额类字段不允许使用 FLOAT/DOUBLE，需使用 DECIMAL', dbType: 'All', builtIn: true },
  { id: 'DDL-021', name: '字段注释检查', category: 'Audit', level: 'LOW', status: 'enabled', description: '所有字段必须添加 COMMENT 注释说明', dbType: 'MySQL', builtIn: true },
  { id: 'DDL-022', name: '默认值检查', category: 'Structure', level: 'LOW', status: 'enabled', description: '字符类型字段建议设置 DEFAULT 值', dbType: 'All', builtIn: true },
  { id: 'DDL-023', name: '表注释检查', category: 'Audit', level: 'LOW', status: 'enabled', description: '建表语句必须包含 TABLE COMMENT', dbType: 'MySQL', builtIn: true },
  { id: 'DDL-024', name: 'VARCHAR 最大长度', category: 'Type', level: 'LOW', status: 'disabled', description: 'VARCHAR 最大长度不得超过 1000', dbType: 'All', builtIn: false },
];
