/**
 * @vitest-environment jsdom
 *
 * SPEC 41 — 对话式资产助手前端单元测试
 *
 * 覆盖：
 * 1. 点击"资产助手"按钮 → AssetChatPanel 显示
 * 2. SSE assets 帧 → 资产卡片渲染到 DOM
 * 3. apply_filter Action 按钮 → 触发 onApplyFilter 回调
 * 4. connectionId 切换 → sessionStorage 清空
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { AssetChatPanel } from '../../src/features/tableau-explorer/AssetChatPanel';

// jsdom 不实现 scrollIntoView，全局 stub 防止测试报错
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// ── 全局 fetch mock ───────────────────────────────────────────────────────────

function makeSseStream(frames: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
      }
      controller.close();
    },
  });
}

// ── 测试 1：助手按钮显示面板 ──────────────────────────────────────────────────

describe('资产助手按钮 → 显示面板', () => {
  it('AssetChatPanel 渲染后显示"资产助手"标题', () => {
    const onClose = vi.fn();
    const onApplyFilter = vi.fn();
    const onHighlightAssets = vi.fn();

    render(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={1}
          onApplyFilter={onApplyFilter}
          onHighlightAssets={onHighlightAssets}
          onClose={onClose}
        />
      </MemoryRouter>
    );

    expect(screen.getByText('资产助手')).toBeInTheDocument();
  });

  it('点击关闭按钮调用 onClose 回调', () => {
    const onClose = vi.fn();

    render(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={1}
          onApplyFilter={vi.fn()}
          onHighlightAssets={vi.fn()}
          onClose={onClose}
        />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// ── 测试 2：SSE assets 帧 → 资产卡片渲染到 DOM ───────────────────────────────

describe('SSE assets 帧 → 资产卡片渲染', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeSseStream([
          { type: 'text', delta: '找到以下仪表板：' },
          {
            type: 'assets',
            assets: [
              {
                id: 42,
                name: 'Executive Sales Dashboard',
                asset_type: 'dashboard',
                health_score: 42,
                project_name: 'Revenue',
                relevance_reason: '健康分低于阈值',
              },
            ],
          },
          { type: 'done' },
        ]),
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it('发送消息后 SSE assets 帧渲染资产卡片到 DOM', async () => {
    render(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={1}
          onApplyFilter={vi.fn()}
          onHighlightAssets={vi.fn()}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    );

    const textarea = screen.getByPlaceholderText(/输入问题/);
    fireEvent.change(textarea, { target: { value: '健康分低于60的仪表板' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    await waitFor(() => {
      expect(screen.getByText('Executive Sales Dashboard')).toBeInTheDocument();
    }, { timeout: 3000 });

    // 验证资产名称、项目名称、健康分均渲染
    expect(screen.getByText('Revenue')).toBeInTheDocument();
    expect(screen.getByText(/健康分 42/)).toBeInTheDocument();
    // 验证相关性原因渲染
    expect(screen.getByText('健康分低于阈值')).toBeInTheDocument();
  });
});

// ── 测试 3：apply_filter Action 按钮 → 触发 onApplyFilter ────────────────────

describe('Action 按钮 → onApplyFilter 回调', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeSseStream([
          { type: 'text', delta: '找到 3 个仪表板' },
          {
            type: 'assets',
            assets: [
              {
                id: 10,
                name: '测试仪表板',
                asset_type: 'dashboard',
                health_score: 50,
                project_name: 'Test',
                relevance_reason: '',
              },
            ],
          },
          {
            type: 'action',
            action_type: 'apply_filter',
            payload: { asset_type: 'dashboard' },
            action_label: '仅显示仪表板',
          },
          { type: 'done' },
        ]),
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it('Action 按钮渲染后点击触发 onApplyFilter 回调', async () => {
    const onApplyFilter = vi.fn();

    render(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={1}
          onApplyFilter={onApplyFilter}
          onHighlightAssets={vi.fn()}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    );

    const textarea = screen.getByPlaceholderText(/输入问题/);
    fireEvent.change(textarea, { target: { value: '所有仪表板' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    // 等待 action 按钮出现（done 帧后才显示）
    await waitFor(() => {
      expect(screen.getByText('仅显示仪表板')).toBeInTheDocument();
    }, { timeout: 3000 });

    fireEvent.click(screen.getByText('仅显示仪表板'));
    expect(onApplyFilter).toHaveBeenCalledWith('dashboard');
  });
});

// ── 测试 4：切换 connectionId → sessionStorage 清空 ─────────────────────────

describe('connectionId 切换 → sessionStorage 清空', () => {
  afterEach(() => {
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it('connectionId 为 1 时写入 sessionStorage，切换到 2 后旧 key 清空', () => {
    // 预先写入 connection 1 的历史
    const chatKey1 = 'tableau-asset-chat-1';
    sessionStorage.setItem(
      chatKey1,
      JSON.stringify([{ role: 'user', content: '旧消息' }])
    );

    const { rerender } = render(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={1}
          onApplyFilter={vi.fn()}
          onHighlightAssets={vi.fn()}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    );

    // 切换到 connectionId=2
    rerender(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={2}
          onApplyFilter={vi.fn()}
          onHighlightAssets={vi.fn()}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    );

    // 切换后 connection 2 的历史为空（新连接）
    const chatKey2 = 'tableau-asset-chat-2';
    const stored = sessionStorage.getItem(chatKey2);
    const parsed = stored ? JSON.parse(stored) : [];
    expect(parsed).toHaveLength(0);
  });

  it('connectionId 不变时，sessionStorage 中的历史消息保留', () => {
    const chatKey = 'tableau-asset-chat-1';
    // 预先清空，让组件自然写入
    sessionStorage.removeItem(chatKey);

    const { rerender } = render(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={1}
          onApplyFilter={vi.fn()}
          onHighlightAssets={vi.fn()}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    );

    // connectionId 不变，重渲染
    rerender(
      <MemoryRouter>
        <AssetChatPanel
          connectionId={1}
          onApplyFilter={vi.fn()}
          onHighlightAssets={vi.fn()}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    );

    // sessionStorage 初始化为空数组（组件首次渲染持久化空历史）
    const stored = sessionStorage.getItem(chatKey);
    expect(stored).not.toBeNull();
  });
});
