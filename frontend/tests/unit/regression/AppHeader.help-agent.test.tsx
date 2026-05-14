/**
 * @vitest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import AppHeader from '../../../src/components/layout/AppHeader';

vi.mock('../../../src/context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 1,
      username: 'admin',
      display_name: 'Admin',
      role: 'admin',
      avatar_url: null,
    },
    logout: vi.fn(),
    hasPermission: () => true,
  }),
}));

vi.mock('../../../src/api/notifications', () => ({
  getUnreadCount: vi.fn().mockResolvedValue(0),
  listNotifications: vi.fn().mockResolvedValue({ items: [] }),
  markNotificationRead: vi.fn(),
  markNotificationUnread: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  deleteNotification: vi.fn(),
}));

describe('AppHeader Help Agent 入口', () => {
  it('在消息通知左侧渲染 icon-only 入口并打开 Help Agent', async () => {
    const onOpenHelpAgent = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <AppHeader onOpenHelpAgent={onOpenHelpAgent} />
      </MemoryRouter>
    );

    const helpButton = screen.getByRole('button', { name: '打开 Help Agent' });
    const notificationButton = screen.getByRole('button', { name: '消息通知' });

    expect(helpButton).toHaveAttribute('title', '打开 Help Agent');
    expect(helpButton.querySelector('.ri-robot-2-line')).not.toBeNull();
    expect(helpButton.compareDocumentPosition(notificationButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.click(helpButton);

    expect(onOpenHelpAgent).toHaveBeenCalledTimes(1);
  });

  it('点击 Help Agent 时关闭通知下拉和用户菜单', async () => {
    const onOpenHelpAgent = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <AppHeader onOpenHelpAgent={onOpenHelpAgent} />
      </MemoryRouter>
    );

    const helpButton = screen.getByRole('button', { name: '打开 Help Agent' });

    await user.click(screen.getByRole('button', { name: '消息通知' }));
    expect(screen.getByText('查看全部消息')).toBeInTheDocument();
    await user.click(helpButton);
    expect(screen.queryByText('查看全部消息')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'A Admin' }));
    expect(screen.getByText('账号设置')).toBeInTheDocument();
    await user.click(helpButton);
    expect(screen.queryByText('账号设置')).not.toBeInTheDocument();
    expect(onOpenHelpAgent).toHaveBeenCalledTimes(2);
  });
});
