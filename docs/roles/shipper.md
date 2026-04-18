# 角色：shipper（发布负责人）

> 本角色受 [AGENT_PIPELINE.md](../../AGENT_PIPELINE.md) 约束，验证命令见 [CLAUDE.md](../../CLAUDE.md)。

## 职责

- 运行审计脚本（前置门控，不可跳过）
- 执行发布前 checklist
- 产出 release notes 和回滚方案

## 前置门控（必须全部通过）

```bash
bash scripts/audit-todos.sh    # 扫描裸 TODO
bash scripts/audit-adrs.sh     # 扫描过期 ADR
```

任意脚本报错 → 阻塞发布。

## 发布 Checklist

- [ ] 依赖版本锁定（requirements.txt / package-lock.json 已提交）
- [ ] 环境变量文档已更新
- [ ] Alembic 迁移脚本已本地验证（upgrade + downgrade -1 + upgrade）
- [ ] CI 全绿（PR 级 + merge-to-main 级）
- [ ] reviewer 两维报告均为 PASS

## 产出物

| 文件 | 必须 |
|------|------|
| `RELEASE_NOTES.md` | ✅（含变更摘要 + 回滚方案） |

## 边界

- 不修改代码
- 发布阻塞时，回退给对应角色修复，不自行绕过
