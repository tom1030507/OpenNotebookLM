import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import ChatArea from './chat/ChatArea';
import StudioPanel from './layout/StudioPanel';
import TopNav from './layout/TopNav';


describe('workspace control availability', () => {
  it('disables the source entry points and explains how to enable them without a project', () => {
    const markup = renderToStaticMarkup(createElement(ChatArea));
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
});
