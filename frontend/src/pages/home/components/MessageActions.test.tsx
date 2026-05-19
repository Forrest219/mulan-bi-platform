import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MessageActions } from './MessageActions';

describe('MessageActions feedback identity', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ rating: null }),
        }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('loads existing feedback by run_id when available', async () => {
    render(
      <MessageActions
        content="answer"
        conversationId="conversation-1"
        messageIndex={1}
        question="question"
        traceId="74cb5871-ce97-498f-b94b-70e6c6c7ae91"
      />,
    );

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/agent/feedback?run_id=74cb5871-ce97-498f-b94b-70e6c6c7ae91',
        { credentials: 'include' },
      );
    });
  });

  it('posts run_id with new feedback', async () => {
    render(
      <MessageActions
        content="answer"
        conversationId="conversation-1"
        messageIndex={1}
        question="question"
        traceId="ee3feecc-6c78-4515-a413-21ea7872e4e4"
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: '有用' }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(2);
    });
    const [, postOptions] = (fetch as ReturnType<typeof vi.fn>).mock.calls[1];
    expect(postOptions).toMatchObject({
      method: 'POST',
      credentials: 'include',
    });
    expect(JSON.parse(String(postOptions.body))).toMatchObject({
      run_id: 'ee3feecc-6c78-4515-a413-21ea7872e4e4',
      rating: 'up',
    });
  });

  it('keeps regenerate actions visible when regenerate is available', () => {
    const onRegenerate = vi.fn();

    render(
      <MessageActions
        content="answer"
        conversationId="conversation-1"
        messageIndex={1}
        question="整体的销售额、利润、利润率、客户数、客单价是什么样子"
        traceId="0c868da0-6c52-4605-a963-571cd1c62e57"
        onRegenerate={onRegenerate}
      />,
    );

    const regenerateButton = screen.getByRole('button', { name: '重新生成' });
    expect(regenerateButton.parentElement).toHaveClass('opacity-100');
    expect(regenerateButton.parentElement).not.toHaveClass('opacity-0');
  });
});
