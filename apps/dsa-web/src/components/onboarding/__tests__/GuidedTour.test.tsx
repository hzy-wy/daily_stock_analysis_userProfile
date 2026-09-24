import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GuidedTour } from '../GuidedTour';

describe('GuidedTour', () => {
  afterEach(() => vi.restoreAllMocks());

  it('advances when the user clicks the real highlighted control', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 80,
      y: 100,
      top: 100,
      right: 320,
      bottom: 148,
      left: 80,
      width: 240,
      height: 48,
      toJSON: () => ({}),
    });

    const onClose = vi.fn();
    render(
      <>
        <button type="button" data-onboarding="test-target">真实控件</button>
        <GuidedTour
          isOpen
          language="zh"
          roleLabel="普通用户"
          steps={[
            {
              id: 'interactive',
              eyebrow: '第一步',
              title: '点击高亮控件',
              description: '这是一个交互步骤。',
              target: '[data-onboarding="test-target"]',
              advanceOnTargetClick: true,
            },
            {
              id: 'finished',
              eyebrow: '第二步',
              title: '已经进入下一步',
              description: '真实点击会推进导览。',
            },
          ]}
          onClose={onClose}
        />
      </>,
    );

    await waitFor(() => expect(document.querySelector('.onboarding-tour__spotlight')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '真实控件' }));

    expect(await screen.findByRole('heading', { name: '已经进入下一步' }))
      .toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('commits the next step immediately without an artificial transition wait', () => {
    render(
      <GuidedTour
        isOpen
        language="zh"
        roleLabel="普通用户"
        steps={[
          {
            id: 'first',
            eyebrow: '第一步',
            title: '当前步骤',
            description: '准备切换。',
          },
          {
            id: 'second',
            eyebrow: '第二步',
            title: '下一模块',
            description: '无需等待退出动画。',
          },
        ]}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '下一步' }));
    expect(screen.getByRole('heading', { name: '下一模块' })).toBeInTheDocument();
  });
});
