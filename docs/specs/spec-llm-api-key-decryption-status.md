# SPEC 修正：LLM API Key 可解密状态标识

| 属性 | 值 |
|------|-----|
| 修正编号 | spec-llm-key-decryption-status |
| 日期 | 2026-04-30 |
| 修正范围 | Spec-08 §2.2 `to_dict()` 返回字段、§6 错误码 |
| 状态 | 草稿 |
| 提出者 | UAT |
| 关联 Spec | spec-08-llm-layer-v1.3 |

---

## 背景

`LLMConfig.to_dict()` 方法解密存储的 `api_key_encrypted` 时，可能因以下原因失败：

- 环境变量 `LLM_ENCRYPTION_KEY` 被轮换（旧密文无法用新密钥解密）
- 数据库从备份恢复，数据与当前密钥不匹配
- 加密密钥配置错误

**当前行为**：解密失败时降级为固定掩码 `"••••••••"`，`has_api_key` 仍为 `true`，前端无法区分"Key 正常"和"Key 已损坏"。

**期望行为**：前端应能明确感知"Key 已损坏，需重新保存"。

---

## 修正内容

### 1. `to_dict()` 新增字段 `api_key_decryption_ok`

**Spec-08 §2.2 `to_dict()` 返回字段** 修正如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_api_key` | `bool` | api_key_encrypted 字段是否非空（仅检查存储存在，不验证可解密性） |
| `api_key_decryption_ok` | `bool` | **【新增】** 加密存储的 Key 当前是否可用（解密成功=true，失败=false） |
| `api_key_preview` | `string\|null` | 脱敏预览，能解密时为真实掩码格式如 `sk-•••••••••3f2a`，无法解密时为 `"••••••••"` |

**`to_dict()` 逻辑变更**：

```python
def to_dict(self):
    decrypted = None
    decryption_ok = False          # 【新增】初始化标志
    if self.api_key_encrypted:
        try:
            from services.llm.service import _decrypt
            decrypted = _decrypt(self.api_key_encrypted)
            decryption_ok = True   # 【新增】解密成功时设为 True
        except Exception:
            pass                    # 解密失败，decryption_ok 保持 False

    api_key_preview = ...
    return {
        ...
        "has_api_key": bool(self.api_key_encrypted),
        "api_key_decryption_ok": decryption_ok,   # 【新增】
        "api_key_preview": api_key_preview,
        ...
    }
```

### 2. API 错误码扩展（Spec-08 §6）

| 错误码 | HTTP 状态码 | 触发条件 | 错误消息 |
|--------|------------|----------|---------|
| `LLM_002` | 400 | API Key 解密失败（密钥不匹配或数据损坏） | API Key 无法解密，可能已被更换加密密钥。请重新保存此配置。 |

**现有 Spec-08 §6** 中 `LLM_002` 的描述为"API Key 无效"。本修正将其触发条件明确为解密失败，并在 `POST /api/llm/config/test` 接口的 `config_id` 路径上实现。

---

## 前端 UI 联动

### ApiKeyCell 组件（`llm-configs/page.tsx`）

| `has_api_key` | `api_key_decryption_ok` | UI 展示 |
|----------------|------------------------|---------|
| `false` | — | 红点 + "未配置" + "去设置" 按钮 |
| `true` | `false` | 红点 + "Key 已损坏" + "重新保存" 按钮 |
| `true` | `true` | 正常显示脱敏 Key + 更新时间 |

### 行内"测试"按钮

当 `api_key_decryption_ok === false` 时：
- 按钮 `disabled`
- `title` 提示"API Key 已损坏，请重新保存"

### 测试连接 API（`POST /api/llm/config/test`）

当 `config_id` 路径解密失败时，返回：
```json
{
  "success": false,
  "message": "API Key 无法解密，可能已被更换加密密钥。请重新保存此配置。",
  "error_code": "LLM_002"
}
```

---

## 数据库影响

**无新增字段**。本修正仅在 ORM `to_dict()` 返回值层面增加派生字段，不涉及表结构变更。

---

## 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-04-30 | spec-llm-key-decryption-status | 新增 `api_key_decryption_ok` 字段；明确 `LLM_002` 在解密失败场景的返回消息 |
