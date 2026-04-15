/**
 * @vitest-environment jsdom
 * AskBar Component Tests (P5 T7)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { AskBar } from '../../../../src/pages/home/components/AskBar';

const mockAskQuestion = vi.fn();
vi.mock('../../../../src/api/search', () => ({
  askQuestion: (...args: unknown[]) => mockAskQuestion(...args),
}));

describe('AskBar', () => {
  beforeEach(() => {
    mockAskQuestion.mockReset();
  });

  it('空输入不触发提交', async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    const onError = vi.fn();
    const onLoading = vi.fn();
    render(<AskBar onResult={onResult} onError={onError} onLoading={onLoading} />);
    const textarea = screen.getByRole('textbox');
    // textarea starts empty — pressing Enter should not trigger submission
    await user.keyboard('{Enter}');
    expect(onResult).not.toHaveBeenCalled();
  });

  it('Enter 键触发提交', async () => {
    const user = userEvent.setup();
    mockAskQuestion.mockResolvedValue({ answer: 'test', type: 'text' });
    const onResult = vi.fn();
    const onError = vi.fn();
    const onLoading = vi.fn();
    render(<AskBar onResult={onResult} onError={onError} onLoading={onLoading} />);
    const textarea = screen.getByRole('textbox');
    await user.type(textarea, 'Q1 销售额是多少');
    await user.keyboard('{Enter}');
    expect(mockAskQuestion).toHaveBeenCalledWith({ question: 'Q1 销售额是多少' });
  });

  it('提交中禁用输入', async () => {
    const user = userEvent.setup();
    mockAskQuestion.mockImplementation(() => new Promise(() => {}));
    const onResult = vi.fn();
    const onError = vi.fn();
    const onLoading = vi.fn();
    render(<AskBar onResult={onResult} onError={onError} onLoading={onLoading} />);
    const textarea = screen.getByRole('textbox');
    await user.type(textarea, 'Q1 销售额');
    await user.keyboard('{Enter}');
    expect(textarea).toBeDisabled();
  });

  it('超长输入被截断在 500 字符', async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    const onError = vi.fn();
    const onLoading = vi.fn();
    render(<AskBar onResult={onResult} onError={onError} onLoading={onLoading} />);
    const textarea = screen.getByRole('textbox');
    await user.type(textarea, 'a'.repeat(600));
    expect((textarea as HTMLTextAreaElement).value.length).toBe(500);
  });
});
