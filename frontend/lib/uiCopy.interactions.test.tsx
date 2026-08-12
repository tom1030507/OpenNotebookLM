import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import Settings from '@/components/Settings';
import { UserMenu } from '@/components/layout/TopNav';

describe('Traditional Chinese interactive workspace copy', () => {
  it('renders the opened user menu in Traditional Chinese', () => {
    const markup = renderToStaticMarkup(
      <UserMenu isOpen onToggle={() => undefined} onOpenSettings={() => undefined} />,
    );

    expect(markup).toContain('使用者');
    expect(markup).toContain('個人資料');
    expect(markup).not.toMatch(/>User<|>Profile</);
  });

  it('renders every settings tab label in Traditional Chinese', () => {
    const markup = renderToStaticMarkup(<Settings isOpen onClose={() => undefined} />);

    expect(markup).toContain('一般');
    expect(markup).toContain('API 金鑰');
    expect(markup).toContain('資料與儲存空間');
    expect(markup).toContain('通知');
    expect(markup).toContain('安全性');
    expect(markup).toContain('關於');
    expect(markup).not.toMatch(/>Settings<|>API Key<|>Data & Storage<|>Notifications<|>Security<|>About</);
  });
});
