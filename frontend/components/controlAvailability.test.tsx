import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';

import ChatArea from './chat/ChatArea';
import StudioPanel from './layout/StudioPanel';
import SourcesPanel from './layout/SourcesPanel';
import TopNav from './layout/TopNav';
import {
  closeAddSourcesAfterSuccessfulUpload,
  requestAddSources,
} from './sourceActions';
import type { Project } from '@/lib/api';
import useStore from '@/store/useStore';


const currentProject: Project = {
  id: 'project-1',
  name: '研究筆記',
  description: null,
  meta_json: {},
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
  document_count: 0,
  conversation_count: 0,
};


afterEach(() => {
  Object.assign(useStore.getInitialState(), {
    currentProject: null,
    documents: [],
    messages: [],
  });
});


describe('workspace control availability', () => {
  it('disables the source entry points without a project', () => {
    const markup = renderToStaticMarkup(createElement(ChatArea, {
      onAddSourcesOpenChange: () => undefined,
    }));
    const uploadButton = markup.match(/<button[^>]*aria-label="上傳來源"[^>]*>/)?.[0];
    const attachmentButton = markup.match(/<button[^>]*aria-label="新增來源"[^>]*>/)?.[0];

    expect(uploadButton).toContain('disabled=""');
    expect(attachmentButton).toContain('disabled=""');
    expect(markup).toContain('請先選擇或建立專案後再新增來源');
    expect(markup).not.toContain('hover:shadow-sm transition-base cursor-pointer');
  });

  it('marks inactive studio, notification, and help controls as disabled and coming soon', () => {
    const studioButtons = renderToStaticMarkup(createElement(StudioPanel)).match(/<button[^>]*>/g) || [];
    const topNavMarkup = renderToStaticMarkup(createElement(TopNav));
    const notificationButton = topNavMarkup.match(/<button[^>]*aria-label="通知功能即將推出"[^>]*>/)?.[0];
    const helpButton = topNavMarkup.match(/<button[^>]*aria-label="說明功能即將推出"[^>]*>/)?.[0];

    expect(studioButtons).not.toHaveLength(0);
    expect(studioButtons.every((button) => button.includes('disabled=""'))).toBe(true);
    expect(notificationButton).toContain('disabled=""');
    expect(helpButton).toContain('disabled=""');
    expect(topNavMarkup).toContain('即將推出');
  });

  it('enables source entry points and renders the Add Sources dialog for a project', () => {
    Object.assign(useStore.getInitialState(), { currentProject });

    const chatMarkup = renderToStaticMarkup(createElement(ChatArea, {
      onAddSourcesOpenChange: () => undefined,
    }));
    const uploadButton = chatMarkup.match(/<button[^>]*aria-label="上傳來源"[^>]*>/)?.[0];
    const attachmentButton = chatMarkup.match(/<button[^>]*aria-label="新增來源"[^>]*>/)?.[0];
    const sourcesMarkup = renderToStaticMarkup(createElement(SourcesPanel, {
      isAddSourcesOpen: true,
      onAddSourcesOpenChange: () => undefined,
    }));

    expect(uploadButton).not.toContain('disabled=""');
    expect(attachmentButton).not.toContain('disabled=""');
    expect(sourcesMarkup).toContain('role="dialog"');
    expect(sourcesMarkup).toContain('aria-modal="true"');
  });

  it('opens Add Sources only when a project is selected', () => {
    let isAddSourcesOpen = false;
    const onAddSourcesOpenChange = (isOpen: boolean) => {
      isAddSourcesOpen = isOpen;
    };

    requestAddSources(false, onAddSourcesOpenChange);
    expect(isAddSourcesOpen).toBe(false);

    requestAddSources(true, onAddSourcesOpenChange);
    expect(isAddSourcesOpen).toBe(true);
  });

  it('closes Add Sources only after a successful upload', async () => {
    let isAddSourcesOpen = true;
    const uploadedSources: string[] = [];
    const onAddSourcesOpenChange = (isOpen: boolean) => {
      isAddSourcesOpen = isOpen;
    };

    await closeAddSourcesAfterSuccessfulUpload(async () => {
      uploadedSources.push('來源');
    }, onAddSourcesOpenChange);

    expect(uploadedSources).toEqual(['來源']);
    expect(isAddSourcesOpen).toBe(false);
  });

  it('keeps Add Sources open after a failed upload', async () => {
    let isAddSourcesOpen = true;
    const uploadError = new Error('上傳失敗');
    const onAddSourcesOpenChange = (isOpen: boolean) => {
      isAddSourcesOpen = isOpen;
    };

    await expect(closeAddSourcesAfterSuccessfulUpload(async () => {
      throw uploadError;
    }, onAddSourcesOpenChange)).rejects.toThrow(uploadError);

    expect(isAddSourcesOpen).toBe(true);
  });
});
