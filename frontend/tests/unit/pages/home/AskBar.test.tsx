/**
 * @vitest-environment jsdom
 * AskBar Component Tests (P5 T7) — updated for default export + streaming arch
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import AskBar from '../../../../src/pages/home/components/AskBar';

// ── Context mocks ────────────────────────────────────────────────────────────
vi.mock('../../../../src/pages/home/context/ScopeContext', () => ({
  useScope: () => ({
    connections: [{ id: 1, name: 'Test Connection', is_active: true }],
    connectionsLoading: false,
    connectionId: '1',
    scopeProject: null,
  }),
}));

vi.mock('../../../../src/api/tableau', () => ({
  listConnections: () => Promise.resolve({ connections: [] }),
}));

// ── Helpers ──────────────────────────────────────────────────────────────────
const defaultProps = {
  onResult: vi.fn(),
  onError: vi.fn(),
  onLoading: vi.fn(),
};

function renderAskBar(props = {}) {
  return render(
    <MemoryRouter>
      <AskBar {...defaultProps} {...props} />
    </MemoryRouter>
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────
describe('AskBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('空输入不触发提交', async () => {
    const user = userEvent.setup();
    renderAskBar();
    const textarea = screen.getByRole('textbox');
    await user.click(textarea);
    await user.keyboard('{Enter}');
    expect(defaultProps.onLoading).not.toHaveBeenCalled();
  });

  it('Enter 键触发 onLoading(true)', async () => {
    const user = userEvent.setup();
    renderAskBar({ useMock: false });
    const textarea = screen.getByRole('textbox');
    await user.type(textarea, 'Q1 销售额是多少');
    await user.keyboard('{Enter}');
    expect(defaultProps.onLoading).toHaveBeenCalledWith(true);
  });

  it('提交后输入框被清空', async () => {
    const user = userEvent.setup();
    renderAskBar({ useMock: false });
    const textarea = screen.getByRole('textbox');
    await user.type(textarea, '华南区销售数据');
    await user.keyboard('{Enter}');
    expect((textarea as HTMLTextAreaElement).value).toBe('');
  });

  it('超长输入被截断在 500 字符', async () => {
    const user = userEvent.setup();
    renderAskBar();
    const textarea = screen.getByRole('textbox');
    await user.type(textarea, 'a'.repeat(600));
    expect((textarea as HTMLTextAreaElement).value.length).toBe(500);
  });
});
