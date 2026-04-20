module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // ── 类型枚举 ────────────────────────────────────────────────
    // 仅允许 feat / fix / docs / style / refactor / perf / test / chore
    'type-enum': [
      2,
      'always',
      [
        'feat',   // 新功能
        'fix',    // 错误修复
        'refactor', // 重构，不涉及功能变更
        'perf',   // 性能优化
        'docs',   // 文档更新
        'style',  // 代码格式（不影响运行）
        'test',   // 测试相关
        'chore',  // 构建/维护任务
      ],
    ],

    // ── 类型大小写 ──────────────────────────────────────────────
    'type-case': [2, 'always', 'lower-case'],

    // ── 类型与冒号之间有空格 ─────────────────────────────────────
    'type-empty': [2, 'never'],

    // ── subject 非空 ────────────────────────────────────────────
    'subject-empty': [2, 'never'],

    // ── subject 结尾不加点 ─────────────────────────────────────
    'subject-full-stop': [2, 'never', '.'],

    // ── header 最多 72 字符 ────────────────────────────────────
    'header-max-length': [2, 'always', 72],

    // ── body 每行最多 100 字符 ─────────────────────────────────
    'body-max-line-length': [2, 'always', 100],
  },
};
