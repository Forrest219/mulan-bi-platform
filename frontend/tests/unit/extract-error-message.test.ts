import { describe, it, expect } from 'vitest';
import { extractErrorMessage } from '../../src/api/tableau';

describe('extractErrorMessage', () => {
  it('纯字符串 detail 直接返回', () => {
    expect(extractErrorMessage({ detail: '连接不存在' }, '兜底')).toBe('连接不存在');
  });

  it('结构化 detail 提取 message 字段', () => {
    const err = { detail: { error_code: 'TAB_002', message: '无权访问此连接', detail: {} } };
    expect(extractErrorMessage(err, '兜底')).toBe('无权访问此连接');
  });

  it('detail 为空对象时返回 fallback', () => {
    expect(extractErrorMessage({ detail: {} }, '同步失败')).toBe('同步失败');
  });

  it('无 detail 字段时返回 fallback', () => {
    expect(extractErrorMessage({ other: 'x' }, '操作失败')).toBe('操作失败');
  });

  it('null 输入返回 fallback', () => {
    expect(extractErrorMessage(null, '请求失败')).toBe('请求失败');
  });

  it('非对象输入返回 fallback', () => {
    expect(extractErrorMessage('string', '请求失败')).toBe('请求失败');
    expect(extractErrorMessage(42, '请求失败')).toBe('请求失败');
  });

  it('detail.message 非字符串时返回 fallback', () => {
    expect(extractErrorMessage({ detail: { message: 123 } }, '兜底')).toBe('兜底');
  });
});
