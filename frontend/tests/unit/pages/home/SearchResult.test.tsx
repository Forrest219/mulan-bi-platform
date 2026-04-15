/**
 * @vitest-environment jsdom
 * SearchResult Component Tests (P5 T7)
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { SearchResult } from '../../../../src/pages/home/components/SearchResult';
import type { SearchAnswer } from '../../../../src/api/search';

describe('SearchResult', () => {
  it('type=number 渲染 NumberCard', () => {
    const result: SearchAnswer = {
      answer: 'Q1 销售额为 1,234,567 元',
      type: 'number',
      data: { value: 1234567, unit: '元', formatted: '1,234,567' },
      confidence: 0.92,
    };
    render(<SearchResult result={result} onRetry={vi.fn()} />);
    expect(screen.getByText('1,234,567')).toBeTruthy();
    expect(screen.getByText('元')).toBeTruthy();
  });

  it('type=table 渲染 TableResult，超过 10 行显示截断提示', () => {
    const columns = ['产品', '销售额'];
    const rows = Array.from({ length: 15 }, (_, i) => ({ 产品: `产品${i}`, 销售额: i * 100 }));
    const result: SearchAnswer = {
      answer: '',
      type: 'table',
      data: { columns, rows },
    };
    render(<SearchResult result={result} onRetry={vi.fn()} />);
    expect(screen.getByText(/已截断显示前 10 行/)).toBeTruthy();
  });

  it('type=error 渲染 ErrorCard，未知 code fallback UNKNOWN', () => {
    const result: SearchAnswer = {
      answer: '',
      type: 'error',
      reason: 'NLQ_999',
      detail: 'Something went wrong',
    };
    render(<SearchResult result={result} onRetry={vi.fn()} />);
    expect(screen.getByText('未知错误')).toBeTruthy();
  });

  it('confidence<0.6 显示警告徽章', () => {
    const result: SearchAnswer = {
      answer: '',
      type: 'number',
      data: { value: 100, formatted: '100' },
      confidence: 0.4,
    };
    render(<SearchResult result={result} onRetry={vi.fn()} />);
    expect(screen.getByText('AI 不确定')).toBeTruthy();
  });
});
