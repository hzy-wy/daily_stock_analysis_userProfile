import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FloatingStockAssistant } from '../FloatingStockAssistant';

const { chatState, clearCompletionBadge, setCurrentRoute } = vi.hoisted(() => ({
  chatState: { completionBadge: false },
  clearCompletionBadge: vi.fn(),
  setCurrentRoute: vi.fn(),
}));

vi.mock('../../../contexts/UiLanguageContext', () => ({
  useUiLanguage: () => ({ t: (key: string) => key }),
}));

vi.mock('../../../stores/agentChatStore', () => {
  const useAgentChatStore = Object.assign(
    (selector: (state: typeof chatState) => unknown) => selector(chatState),
    {
      getState: () => ({ clearCompletionBadge, setCurrentRoute }),
    },
  );
  return { useAgentChatStore };
});

vi.mock('../../../pages/ChatPage', () => ({
  default: ({ variant }: { variant?: string }) => (
    <div data-testid="assistant-chat-page" data-variant={variant}>shared chat workspace</div>
  ),
}));

describe('FloatingStockAssistant', () => {
  beforeEach(() => {
    chatState.completionBadge = false;
    clearCompletionBadge.mockClear();
    setCurrentRoute.mockClear();
  });

  it('opens the shared chat page in assistant mode without changing routes', async () => {
    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <FloatingStockAssistant />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'assistant.open' }));

    const workspace = await screen.findByTestId('assistant-chat-page');
    expect(workspace).toHaveAttribute('data-variant', 'assistant');
    expect(clearCompletionBadge).toHaveBeenCalledTimes(1);
    expect(setCurrentRoute).toHaveBeenCalledWith('/chat');
  });

  it('moves the completion indication from navigation to the assistant launcher', () => {
    chatState.completionBadge = true;

    render(
      <MemoryRouter initialEntries={['/']}>
        <FloatingStockAssistant />
      </MemoryRouter>,
    );

    expect(screen.getByRole('button', { name: 'assistant.openWithUpdate' })).toBeInTheDocument();
  });

  it('closes with Escape and restores the actual route for completion tracking', async () => {
    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <FloatingStockAssistant />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'assistant.open' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(setCurrentRoute).toHaveBeenLastCalledWith('/portfolio');
  });
});
