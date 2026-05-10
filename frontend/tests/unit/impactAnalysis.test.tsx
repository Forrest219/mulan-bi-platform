/**
 * @vitest-environment jsdom
 *
 * SPEC 40 — 影响分析前端单元测试
 *
 * 覆盖：
 * 1. total_unhealthy_datasources > 0 时 banner 渲染到 DOM
 * 2. total_unhealthy_datasources === 0 时 banner 不渲染
 * 3. ImpactTab 渲染工作簿树（mock getAssetImpact 返回）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import React, { Suspense } from 'react';
import { MemoryRouter } from 'react-router-dom';
import * as tableauApi from '../../src/api/tableau';

// ── 工具：包装 MemoryRouter ──────────────────────────────────────────────────

function wrap(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

// ── ImpactAlerts Banner 测试 ─────────────────────────────────────────────────

/**
 * 最小 Banner 组件（从 AssetExplorer 抽取逻辑，直接单元测试）
 * 避免 mock AssetExplorer 的所有依赖（连接列表 API、资产列表 API 等）
 */
interface BannerProps {
  alerts: tableauApi.ImpactAlertsResult | null;
}

function ImpactAlertBanner({ alerts }: BannerProps) {
  const [show, setShow] = React.useState(false);
  if (!alerts || alerts.total_unhealthy_datasources === 0) return null;
  return (
    <div data-testid="impact-alert-banner" className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span>⚠</span>
        <span data-testid="banner-text" className="text-sm text-orange-700 flex-1">
          {alerts.total_unhealthy_datasources} 个数据源健康异常，影响 {alerts.total_affected_workbooks} 个工作簿
        </span>
        <button data-testid="toggle-btn" onClick={() => setShow(v => !v)}>
          {show ? '收起' : '展开'}
        </button>
      </div>
      {show && (
        <div data-testid="alert-detail">
          {alerts.alerts.map(a => (
            <div key={a.datasource_id} data-testid={`alert-item-${a.datasource_id}`}>
              {a.datasource_name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

describe('ImpactAlertBanner', () => {
  it('total_unhealthy_datasources > 0 时显示 banner', () => {
    const alerts: tableauApi.ImpactAlertsResult = {
      alerts: [
        { datasource_id: 1, datasource_name: 'Sales DB', health_score: 42, affected_workbook_count: 3, affected_view_dashboard_count: 7 },
      ],
      total_unhealthy_datasources: 1,
      total_affected_workbooks: 3,
    };

    wrap(<ImpactAlertBanner alerts={alerts} />);

    expect(screen.getByTestId('impact-alert-banner')).toBeDefined();
    const text = screen.getByTestId('banner-text').textContent;
    expect(text).toContain('1 个数据源健康异常');
    expect(text).toContain('3 个工作簿');
  });

  it('total_unhealthy_datasources === 0 时不渲染 banner', () => {
    const alerts: tableauApi.ImpactAlertsResult = {
      alerts: [],
      total_unhealthy_datasources: 0,
      total_affected_workbooks: 0,
    };

    wrap(<ImpactAlertBanner alerts={alerts} />);
    expect(screen.queryByTestId('impact-alert-banner')).toBeNull();
  });

  it('alerts 为 null 时不渲染 banner', () => {
    wrap(<ImpactAlertBanner alerts={null} />);
    expect(screen.queryByTestId('impact-alert-banner')).toBeNull();
  });

  it('展开时显示告警详情列表', async () => {
    const alerts: tableauApi.ImpactAlertsResult = {
      alerts: [
        { datasource_id: 10, datasource_name: 'Sales DB', health_score: 30, affected_workbook_count: 2, affected_view_dashboard_count: 5 },
        { datasource_id: 11, datasource_name: 'HR Data', health_score: 55, affected_workbook_count: 1, affected_view_dashboard_count: 2 },
      ],
      total_unhealthy_datasources: 2,
      total_affected_workbooks: 3,
    };

    wrap(<ImpactAlertBanner alerts={alerts} />);

    // 点击展开
    screen.getByTestId('toggle-btn').click();

    await waitFor(() => {
      expect(screen.getByTestId('alert-detail')).toBeDefined();
      expect(screen.getByTestId('alert-item-10').textContent).toContain('Sales DB');
      expect(screen.getByTestId('alert-item-11').textContent).toContain('HR Data');
    });
  });
});

// ── ImpactTab 渲染测试 ────────────────────────────────────────────────────────

describe('ImpactTab', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('显示 loading spinner 然后渲染工作簿树', async () => {
    const mockData: tableauApi.AssetImpactResult = {
      datasource: { id: 1, name: 'Sales DB', health_score: 42, asset_type: 'datasource' },
      affected_workbooks: [
        {
          id: 101,
          name: 'Executive Dashboard',
          asset_type: 'workbook',
          affected_views: [
            { id: 201, name: 'Sales Overview', asset_type: 'view' },
            { id: 202, name: 'Revenue Breakdown', asset_type: 'dashboard' },
          ],
        },
      ],
      summary: { workbook_count: 1, view_dashboard_count: 2 },
    };

    vi.spyOn(tableauApi, 'getAssetImpact').mockResolvedValue(mockData);

    // 懒加载方式测试 ImpactTab（直接 import 非懒加载版本用于单元测试）
    const { ImpactTab } = await import('../../src/features/tableau-inspector/tabs/ImpactTab');

    await act(async () => {
      wrap(<ImpactTab assetId="1" />);
    });

    await waitFor(() => {
      // 工作簿名称在 DOM 中
      expect(screen.getByText('Executive Dashboard')).toBeDefined();
      // 汇总数字
      expect(screen.getByText('1')).toBeDefined(); // workbook_count
    });
  });

  it('affected_workbooks 为空时显示"暂无下游工作簿"', async () => {
    const mockData: tableauApi.AssetImpactResult = {
      datasource: { id: 2, name: 'Empty DS', health_score: 80, asset_type: 'datasource' },
      affected_workbooks: [],
      summary: { workbook_count: 0, view_dashboard_count: 0 },
    };

    vi.spyOn(tableauApi, 'getAssetImpact').mockResolvedValue(mockData);

    const { ImpactTab } = await import('../../src/features/tableau-inspector/tabs/ImpactTab');

    await act(async () => {
      wrap(<ImpactTab assetId="2" />);
    });

    await waitFor(() => {
      expect(screen.getByText('该数据源暂无下游工作簿')).toBeDefined();
    });
  });

  it('API 失败时显示错误信息', async () => {
    vi.spyOn(tableauApi, 'getAssetImpact').mockRejectedValue(new Error('获取资产影响分析失败'));

    const { ImpactTab } = await import('../../src/features/tableau-inspector/tabs/ImpactTab');

    await act(async () => {
      wrap(<ImpactTab assetId="99" />);
    });

    await waitFor(() => {
      expect(screen.getByText('获取资产影响分析失败')).toBeDefined();
    });
  });
});
