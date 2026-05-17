import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SyncLogLink } from './SyncLogLink';
import type { TaskRun } from '../../../api/tasks';

function makeRun(result_summary: TaskRun['result_summary']): TaskRun {
  return {
    id: 1,
    celery_task_id: 'task-1',
    task_name: 'services.tasks.tableau_tasks.sync_connection_task',
    task_label: 'Tableau 单连接同步',
    trigger_type: 'manual',
    status: 'succeeded',
    started_at: null,
    finished_at: null,
    duration_ms: null,
    result_summary,
    error_message: null,
    retry_count: 0,
    parent_run_id: null,
    triggered_by: 1,
    created_at: '2026-05-17T00:00:00Z',
  };
}

describe('SyncLogLink', () => {
  it('renders a link when sync_log_id and connection_id are present', () => {
    render(<SyncLogLink run={makeRun({ sync_log_id: 14, connection_id: 4 })} />);

    const link = screen.getByRole('link', { name: '#14' });
    expect(link).toHaveAttribute('href', '/assets/tableau-connections/4/sync-logs');
  });

  it('renders plain text when only sync_log_id is present', () => {
    render(<SyncLogLink run={makeRun({ sync_log_id: 14 })} />);

    expect(screen.getByText('#14')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders a dash when no sync log is associated', () => {
    render(<SyncLogLink run={makeRun(null)} />);

    expect(screen.getByText('-')).toBeInTheDocument();
  });
});
