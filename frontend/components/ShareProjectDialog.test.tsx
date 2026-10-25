// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ShareProjectDialog from './ShareProjectDialog';
import TopNav from './layout/TopNav';
import ProjectDialogProvider from './ProjectDialogProvider';
import api, { type Project, type ProjectMember } from '@/lib/api';
import useStore from '@/store/useStore';

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-10-25T00:00:00Z',
  updated_at: '2026-10-25T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
  role: 'owner',
};

const owner: ProjectMember = {
  user_id: 'user-owner', username: 'owner', email: 'owner@example.com',
  role: 'owner', created_at: '2026-10-25T00:00:00Z',
};
const bob: ProjectMember = {
  user_id: 'user-bob', username: 'bob', email: 'bob@example.com',
  role: 'viewer', created_at: '2026-10-25T00:00:00Z',
};
const carol: ProjectMember = {
  user_id: 'user-carol', username: 'carol', email: 'carol@example.com',
  role: 'editor', created_at: '2026-10-25T00:00:00Z',
};

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useStore.getState().resetForTests();
});

describe('project sharing controls', () => {
  it('lists, adds, changes, and removes members by username or email', async () => {
    const list = vi.spyOn(api, 'getProjectMembers').mockResolvedValue([owner, bob]);
    const add = vi.spyOn(api, 'addProjectMember').mockResolvedValue(carol);
    const update = vi.spyOn(api, 'updateProjectMember').mockResolvedValue({
      ...bob, role: 'editor',
    });
    const remove = vi.spyOn(api, 'removeProjectMember').mockResolvedValue();
    const { rerender } = render(
      <ShareProjectDialog project={project} isOpen onClose={() => undefined} />,
    );

    expect(await screen.findByText('bob@example.com')).toBeTruthy();
    expect(list).toHaveBeenCalledWith(project.id);
    fireEvent.change(screen.getByLabelText('Username or email'), {
      target: { value: 'carol@example.com' },
    });
    fireEvent.change(screen.getByLabelText('Role for new member'), {
      target: { value: 'editor' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add member' }));

    await waitFor(() => expect(add).toHaveBeenCalledWith(project.id, {
      email: 'carol@example.com', role: 'editor',
    }));
    expect(await screen.findByText('carol@example.com')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Role for bob'), {
      target: { value: 'editor' },
    });
    await waitFor(() => expect(update).toHaveBeenCalledWith(
      project.id, bob.user_id, { role: 'editor' },
    ));
    fireEvent.click(screen.getByRole('button', { name: 'Remove bob' }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(project.id, bob.user_id));

    await act(async () => {
      rerender(<ShareProjectDialog project={project} isOpen={false} onClose={() => undefined} />);
    });
  });

  it('marks shared projects and shows the share button only to owners', () => {
    const viewer = { ...project, role: 'viewer' as const };
    useStore.setState({ projects: [viewer], currentProject: viewer });
    const { rerender } = render(
      <ProjectDialogProvider><TopNav /></ProjectDialogProvider>,
    );

    expect(screen.getByText('Shared · Viewer')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Share project' })).toBeNull();

    const ownerProject = { ...project, role: 'owner' as const };
    useStore.setState({ projects: [ownerProject], currentProject: ownerProject });
    rerender(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);
    expect(screen.getByRole('button', { name: 'Share project' })).toBeTruthy();
  });
});
