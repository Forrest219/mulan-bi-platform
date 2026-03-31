# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Removed


## [1.0.0] - 2026-03-31

### Added

- **LLM 能力层 Phase 1**
  - LLM Provider 配置（Provider/Base URL/API Key/Model/Temperature/Max Tokens）
  - 测试连接功能
  - Tableau 资产 AI 摘要（1小时缓存，IDOR 校验）
  - API Key 加密存储（PBKDF2 + Fernet）
  - Anthropic/MiniMax 模型支持

- **Tableau MCP 集成 Phase 1**
  - Tableau 数据源连接管理
  - 工作簿、视图、数据源元数据查询
  - 资产详情查看

- **DDL 规范检查**
  - MySQL/PostgreSQL/SQLite 数据库扫描
  - 规则配置（表命名、字段命名、数据类型、主键/索引、注释、时间戳字段）

- **DDL 生成器**
  - 预置维度表、事实表、ODS、DWD 模板

- **用户权限系统**
  - Session/Cookie 认证 (HTTP Only)
  - 用户组和权限管理
  - 角色：admin, data_admin, analyst, user

- **扫描日志**
  - 操作日志记录
  - SQLite 本地存储

### Security

- JWT 会话令牌验证
- 密码 bcrypt 哈希存储
- 数据源凭据加密
- SQL 注入防护（参数化查询）

---

## Before [1.0.0]

- Initial project setup
- Basic project structure
- Documentation
