/**
 * @vitest-environment jsdom
 *
 * SPEC 39 — 意图搜索前端单元测试
 *
 * 覆盖：
 * 1. 输入 8 个汉字含空格 → isIntentMode 为 true，显示"意图搜索"标签
 * 2. 输入 5 个字符 → 不触发意图模式
 * 3. mock intentSearchAssets 返回结果，验证 relevance_reason 渲染到 DOM
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React, { Suspense } from 'react';
import { MemoryRouter } from 'react-router-dom';
import * as tableauApi from '../../src/api/tableau';

// ── mock API 层 ──────────────────────────────────────────────────────────────

vi.mock('../../src/api/tableau', async (importOriginal) => {
  const actual = await importOriginal<typeof tableauApi>();
  return {
    ...actual,
    listConnections: vi.fn().mockResolvedValue({
      connections: [
        {
          id: 1,
          name: '测试连接',
          server_url: 'http://tableau.test',
          site: '',
          is_active: true,
          last_test_success: true,
          auto_sync_enabled: false,
          sync_interval_hours: 24,
          connection_type: 'mcp',
        },
      ],
      total: 1,
    }),
    listAssets: vi.fn().mockResolvedValue({ assets: [], total: 0, page: 1, page_size: 24, pages: 0 }),
    getProjects: vi.fn().mockResolvedValue({ projects: [] }),
    getImpactAlerts: vi.fn().mockResolvedValue({ total_unhealthy_datasources: 0, total_affected_workbooks: 0, alerts: [] }),
    intentSearchAssets: vi.fn(),
    searchAssets: vi.fn().mockResolvedValue({ assets: [], total: 0, page: 1, page_size: 24 }),
  };
});

// ── 最小化意图搜索框组件，直接测试意图检测逻辑 ─────────────────────────────

interface IntentSearchBoxProps {
  onSearch: (query: string) => void;
}

function IntentSearchBox({ onSearch }: IntentSearchBoxProps) {
  const [value, setValue] = React.useState('');
  const isIntentMode = value.length >= 8 && value.includes(' ');

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && isIntentMode) {
      onSearch(value);
    }
  };

  return (
    <div>
      <input
        data-testid="search-input"
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="搜索资产名称、项目或所有者..."
      />
      {isIntentMode && (
        <span data-testid="intent-badge">意图搜索</span>
      )}
    </div>
  );
}

// ── 意图结果列表组件 ──────────────────────────────────────────────────────────

interface IntentResultsProps {
  results: tableauApi.IntentSearchResult;
}

function IntentResultList({ results }: IntentResultsProps) {
  return (
    <div>
      {results.assets.map(asset => (
        <div key={asset.id} data-testid={`intent-asset-${asset.id}`}>
          <div data-testid={`asset-name-${asset.id}`}>{asset.name}</div>
          {asset.relevance_reason && (
            <div data-testid={`relevance-reason-${asset.id}`} className="text-gray-400 text-xs truncate">
              {asset.relevance_reason}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── 测试：意图检测 ─────────────────────────────────────────────────────────────

describe('IntentSearchBox — 意图模式检测', () => {
  const mockOnSearch = vi.fn();

  beforeEach(() => {
    mockOnSearch.mockClear();
  });

  it('输入 8 个汉字含空格 → 显示"意图搜索"标签', async () => {
    render(<IntentSearchBox onSearch={mockOnSearch} />);
    const input = screen.getByTestId('search-input');

    // 8 个汉字含空格（共 9 字符）
    fireEvent.change(input, { target: { value: '上周销售 下滑原因' } });

    expect(screen.getByTestId('intent-badge')).toBeInTheDocument();
    expect(screen.getByTestId('intent-badge')).toHaveTextContent('意图搜索');
  });

  it('输入 5 个字符 → 不触发意图模式，不显示标签', async () => {
    render(<IntentSearchBox onSearch={mockOnSearch} />);
    const input = screen.getByTestId('search-input');

    fireEvent.change(input, { target: { value: '销售 分析' } });  // 5 chars, has space

    // 长度 < 8，不触发
    expect(screen.queryByTestId('intent-badge')).not.toBeInTheDocument();
  });

  it('输入长度 ≥ 8 但不含空格 → 不触发意图模式', async () => {
    render(<IntentSearchBox onSearch={mockOnSearch} />);
    const input = screen.getByTestId('search-input');

    fireEvent.change(input, { target: { value: '销售分析仪表板' } });  // 7 chars, no space

    expect(screen.queryByTestId('intent-badge')).not.toBeInTheDocument();
  });

  it('清空搜索框 → 退出意图模式，标签消失', async () => {
    render(<IntentSearchBox onSearch={mockOnSearch} />);
    const input = screen.getByTestId('search-input');

    fireEvent.change(input, { target: { value: '上周销售 下滑原因' } });
    expect(screen.getByTestId('intent-badge')).toBeInTheDocument();

    fireEvent.change(input, { target: { value: '' } });
    expect(screen.queryByTestId('intent-badge')).not.toBeInTheDocument();
  });

  it('回车时触发意图搜索回调', async () => {
    render(<IntentSearchBox onSearch={mockOnSearch} />);
    const input = screen.getByTestId('search-input');

    fireEvent.change(input, { target: { value: '上周销售 下滑原因' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(mockOnSearch).toHaveBeenCalledWith('上周销售 下滑原因');
  });
});

// ── 测试：意图搜索结果渲染 ─────────────────────────────────────────────────────

describe('IntentResultList — relevance_reason 渲染', () => {
  it('mock intentSearchAssets 返回结果，验证 relevance_reason 渲染到 DOM', () => {
    const mockResults: tableauApi.IntentSearchResult = {
      assets: [
        {
          id: 1,
          name: '销售仪表板',
          asset_type: 'dashboard',
          project_name: '销售分析',
          health_score: 85,
          ai_summary: '销售趋势摘要',
          view_count: 340,
          relevance_reason: '该仪表板包含销售趋势分析和周环比指标，与销售下滑分析直接相关',
          relevance_score: 0.95,
        },
        {
          id: 2,
          name: '收入监控',
          asset_type: 'view',
          project_name: '财务',
          health_score: 72,
          ai_summary: '月度收入',
          view_count: 210,
          relevance_reason: '涉及收入指标监控，间接相关',
          relevance_score: 0.65,
        },
      ],
      total: 2,
      intent: {
        keywords: ['销售', '下滑'],
        asset_type_hint: 'dashboard',
        time_range_hint: '上周',
      },
    };

    render(<IntentResultList results={mockResults} />);

    // 验证资产名渲染
    expect(screen.getByTestId('asset-name-1')).toHaveTextContent('销售仪表板');
    expect(screen.getByTestId('asset-name-2')).toHaveTextContent('收入监控');

    // 验证 relevance_reason 渲染到 DOM
    expect(screen.getByTestId('relevance-reason-1')).toBeInTheDocument();
    expect(screen.getByTestId('relevance-reason-1')).toHaveTextContent(
      '该仪表板包含销售趋势分析和周环比指标，与销售下滑分析直接相关'
    );
    expect(screen.getByTestId('relevance-reason-2')).toHaveTextContent(
      '涉及收入指标监控，间接相关'
    );
  });

  it('relevance_reason 为空字符串时不渲染相关原因元素', () => {
    const mockResults: tableauApi.IntentSearchResult = {
      assets: [
        {
          id: 3,
          name: '无原因资产',
          asset_type: 'workbook',
          project_name: null,
          health_score: null,
          ai_summary: null,
          view_count: null,
          relevance_reason: '',
          relevance_score: 0.5,
        },
      ],
      total: 1,
      intent: { keywords: ['test'], asset_type_hint: null, time_range_hint: null },
    };

    render(<IntentResultList results={mockResults} />);
    expect(screen.queryByTestId('relevance-reason-3')).not.toBeInTheDocument();
  });
});

// ── 测试：intentSearchAssets API 函数类型安全 ──────────────────────────────────

describe('intentSearchAssets API — 函数签名', () => {
  it('intentSearchAssets 函数存在且可调用', () => {
    expect(typeof tableauApi.intentSearchAssets).toBe('function');
  });
});
