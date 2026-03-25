# DDL Check Engine

> 轻量级 DDL 规则引擎 - 用于校验建表 SQL 是否符合公司规范

## 功能特性

- **DDL 文本解析** - 支持解析 CREATE TABLE 语句
- **规则校验** - 内置 5 条规则（可扩展）
- **结构化输出** - 返回标准 JSON 格式结果

## 安装

```bash
pip install ddl_check_engine
```

或从源码安装：

```bash
git clone https://github.com/Forrest219/ddl_check_engine.git
cd ddl_check_engine
pip install -e .
```

## 快速开始

```python
from ddl_check_engine import DDLCheckEngine, check_ddl

# 使用引擎
engine = DDLCheckEngine()
result = engine.check("CREATE TABLE `dim_user` (...)", db_type="mysql")

# 或使用快捷函数
result = check_ddl("CREATE TABLE `dim_user` (...)", db_type="mysql")

# 查看结果
print(result.passed)       # 是否通过
print(result.score)         # 评分 (0-100)
print(result.executable)    # 是否允许执行
print(result.issues)        # 问题列表
```

## API

### POST /ddl/check

**Request:**
```json
{
  "ddl_text": "CREATE TABLE ...",
  "db_type": "mysql"
}
```

**Response:**
```json
{
  "passed": false,
  "score": 72,
  "summary": {"High": 1, "Medium": 2, "Low": 1},
  "issues": [
    {
      "rule_id": "RULE_001",
      "risk_level": "High",
      "object_type": "table",
      "object_name": "dim_user",
      "description": "表名不符合命名规范",
      "suggestion": "表名必须以小写字母开头"
    }
  ],
  "executable": false
}
```

## 内置规则（一期）

| 规则ID | 规则名称 | 风险等级 |
|--------|----------|----------|
| RULE_001 | 表命名规范 | High |
| RULE_002 | 字段必须有注释 | High |
| RULE_003 | 金额字段类型 | Medium |
| RULE_004 | 必须包含 create_time | High |
| RULE_005 | 必须包含 update_time | High |

## 评分逻辑

```
score = 100 - High*20 - Medium*5 - Low*1
```

- score < 60 → 不允许执行
- 有 High 级问题 → 不允许执行
- score >= 80 且可执行 → 通过

## 项目结构

```
ddl_check_engine/
├── ddl_check_engine/
│   ├── __init__.py
│   ├── engine.py      # 主引擎
│   ├── parser.py      # DDL 解析器
│   └── rules.py       # 规则定义
├── setup.py
└── README.md
```

## License

MIT
