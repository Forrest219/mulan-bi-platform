# Mulan BI Platform - DDL 规范管理平台

> 项目开始日期：2026-03-24
> GitHub：https://github.com/Forrest219/mulan-bi-platform
> 定位：面向 BI 团队的数据表全链路管理平台

## 功能特性

### 核心功能
- [x] DDL 规范检查 - 对现有数据库表单做监控、审查、报警
- [x] DDL 生成器 - 通过配置界面生成符合规范的建表语句
- [x] 扫描日志 - 记录所有扫描操作和结果

### 功能模块
| 模块 | 说明 |
|------|------|
| DDL 规范检查 | 支持 MySQL/PostgreSQL/SQLite 数据库扫描 |
| DDL 生成器 | 预置维度表、事实表、ODS、DWD 模板 |
| 扫描日志 | 记录扫描历史、违规统计、操作记录 |

## 技术栈

- **后端**：Python 3.10+ / SQLAlchemy
- **前端**：Streamlit
- **数据库**：SQLite（本地日志）、MySQL/PostgreSQL（目标数据库）
- **规范规则**：YAML 配置文件

## 快速启动

```bash
# 克隆项目
git clone https://github.com/Forrest219/mulan-bi-platform.git
cd mulan-bi-platform

# 安装依赖
pip install -r requirements.txt

# 启动应用
streamlit run src/main.py
```

## 项目结构

```
mulan-bi-platform/
├── config/              # 配置文件
│   └── rules.yaml       # DDL 规范规则
├── src/                 # 源代码
│   ├── ddl_checker/     # DDL 检查模块
│   ├── ddl_generator/   # DDL 生成模块
│   ├── logs/            # 日志模块
│   └── main.py          # Web 入口
├── data/                # 数据目录（SQLite 日志库）
├── tests/               # 测试用例
├── requirements.txt     # 依赖清单
├── README.md
└── .gitignore
```

## 规范规则

规则配置文件位于 `config/rules.yaml`，可自定义：

- 表命名规范
- 字段命名规范
- 数据类型规范
- 主键/索引规范
- 注释规范
- 时间戳字段规范
- 软删除字段规范

## 团队

- 项目负责人：Forrest219
- BI 团队
