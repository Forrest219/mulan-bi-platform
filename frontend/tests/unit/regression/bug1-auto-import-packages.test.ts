/**
 * 回归测试 Bug 1：
 * vite.config.ts 的 AutoImport imports 配置了未安装的包，导致 Vite 白屏。
 *
 * 检查规则：AutoImport imports 列表中声明的每个包，都必须在 node_modules 里存在。
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// 从 vite.config.ts 源码中解析出 AutoImport imports 里配置的包名
// 使用文本解析方式，不直接 import vite.config.ts（避免引入 vite plugin 副作用）
function extractAutoImportPackages(viteConfigSource: string): string[] {
  // 找到 AutoImport({ imports: [...] }) 块
  // 匹配形如：{ "package-name": [...] } 的对象 key
  const packages: string[] = [];

  // 先截取 AutoImport 调用的内容段
  const autoImportStart = viteConfigSource.indexOf('AutoImport(');
  if (autoImportStart === -1) return packages;

  // 找到 imports: [ 之后的内容
  const importsStart = viteConfigSource.indexOf('imports:', autoImportStart);
  if (importsStart === -1) return packages;

  // 从 imports: 开始，按括号深度找出数组范围
  const arrayStart = viteConfigSource.indexOf('[', importsStart);
  if (arrayStart === -1) return packages;

  let depth = 0;
  let arrayEnd = -1;
  for (let i = arrayStart; i < viteConfigSource.length; i++) {
    if (viteConfigSource[i] === '[') depth++;
    else if (viteConfigSource[i] === ']') {
      depth--;
      if (depth === 0) {
        arrayEnd = i;
        break;
      }
    }
  }
  if (arrayEnd === -1) return packages;

  const importsBlock = viteConfigSource.slice(arrayStart, arrayEnd + 1);

  // 提取对象字面量的 key（单引号或双引号包裹的包名）
  // 形如：{ "react-router-dom": [...] } 或 { react: [...] }
  // 匹配模式：{ key: 或 { "key": 或 { 'key':
  const keyRegex = /\{\s*["']?([\w@/-]+)["']?\s*:/g;
  let match: RegExpExecArray | null;
  while ((match = keyRegex.exec(importsBlock)) !== null) {
    packages.push(match[1]);
  }

  return [...new Set(packages)];
}

const frontendRoot = resolve(__dirname, '../../../');
const viteConfigPath = resolve(frontendRoot, 'vite.config.ts');
const nodeModulesPath = resolve(frontendRoot, 'node_modules');

describe('Bug 1 回归：vite.config.ts AutoImport 引用包均已安装', () => {
  it('vite.config.ts 文件存在', () => {
    expect(existsSync(viteConfigPath), `找不到 ${viteConfigPath}`).toBe(true);
  });

  it('AutoImport imports 中配置的所有包都在 node_modules 中存在', () => {
    const source = readFileSync(viteConfigPath, 'utf-8');
    const packages = extractAutoImportPackages(source);

    expect(packages.length, 'AutoImport imports 应至少包含一个包').toBeGreaterThan(0);

    const missing: string[] = [];
    for (const pkg of packages) {
      const pkgPath = resolve(nodeModulesPath, pkg);
      if (!existsSync(pkgPath)) {
        missing.push(pkg);
      }
    }

    if (missing.length > 0) {
      throw new Error(
        `AutoImport imports 中以下包未安装，会导致 Vite 白屏：\n${missing.map(p => `  - ${p}`).join('\n')}\n` +
        `请执行 npm install ${missing.join(' ')} 或从 vite.config.ts imports 中删除这些条目。`
      );
    }
  });
});
