import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import MessageBubble from './MessageBubble';

describe('MessageBubble markdown asset lists', () => {
  it('renders a single-item markdown list as an asset card', () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content={'#### default（1）\n- [订单+ (示例 - 超市)](https://online.tableau.com/#/site/zy_bi/datasources/8902076)'}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('订单+ (示例 - 超市)')).toBeInTheDocument();
    expect(screen.getByText('查看')).toBeInTheDocument();
  });
});
