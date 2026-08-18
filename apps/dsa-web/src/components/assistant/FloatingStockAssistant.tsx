import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ExternalLink, MessageSquareQuote, Sparkles, X } from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { useAgentChatStore } from '../../stores/agentChatStore';
import { Tooltip } from '../common';

const ChatPage = lazy(() => import('../../pages/ChatPage'));

const PANEL_TRANSITION = {
  type: 'spring' as const,
  stiffness: 360,
  damping: 34,
  mass: 0.82,
};

export const FloatingStockAssistant = () => {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useUiLanguage();
  const reduceMotion = useReducedMotion();
  const completionBadge = useAgentChatStore((state) => state.completionBadge);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const restoreCurrentRoute = useCallback(() => {
    useAgentChatStore.getState().setCurrentRoute(location.pathname);
  }, [location.pathname]);

  const openAssistant = useCallback(() => {
    const chatStore = useAgentChatStore.getState();
    chatStore.clearCompletionBadge();
    chatStore.setCurrentRoute('/chat');
    setIsOpen(true);
  }, []);

  const closeAssistant = useCallback(() => {
    setIsOpen(false);
    restoreCurrentRoute();
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }, [restoreCurrentRoute]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeAssistant();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [closeAssistant, isOpen]);

  useEffect(() => {
    if (location.pathname === '/chat') return undefined;

    const handleShortcut = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || !event.shiftKey || event.key.toLowerCase() !== 'a') {
        return;
      }
      event.preventDefault();
      if (isOpen) {
        closeAssistant();
      } else {
        openAssistant();
      }
    };

    document.addEventListener('keydown', handleShortcut);
    return () => document.removeEventListener('keydown', handleShortcut);
  }, [closeAssistant, isOpen, location.pathname, openAssistant]);

  if (location.pathname === '/login') return null;

  const launcherLabel = completionBadge
    ? t('assistant.openWithUpdate')
    : t('assistant.open');

  return (
    <>
      {location.pathname !== '/chat' ? (
        <motion.button
          ref={triggerRef}
          type="button"
          className="stock-assistant-launcher"
          aria-label={launcherLabel}
          aria-expanded={isOpen}
          aria-controls="stock-assistant-panel"
          onClick={openAssistant}
          whileHover={reduceMotion ? undefined : { y: -3, scale: 1.025 }}
          whileTap={reduceMotion ? undefined : { scale: 0.96 }}
        >
          <span className="stock-assistant-launcher__halo" aria-hidden="true" />
          <span className="stock-assistant-launcher__orb" aria-hidden="true">
            <Sparkles className="h-5 w-5" />
          </span>
          <span className="stock-assistant-launcher__copy">
            <strong>{t('assistant.shortTitle')}</strong>
            <small>{completionBadge ? t('assistant.newReply') : t('assistant.ready')}</small>
          </span>
          {completionBadge ? <span className="stock-assistant-launcher__badge" aria-hidden="true" /> : null}
        </motion.button>
      ) : null}

      {typeof document !== 'undefined'
        ? createPortal(
          <AnimatePresence>
            {isOpen ? (
              <div className="stock-assistant-layer" role="presentation">
                <motion.button
                  type="button"
                  className="stock-assistant-backdrop"
                  aria-label={t('assistant.close')}
                  onClick={closeAssistant}
                  initial={reduceMotion ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0 }}
                />
                <motion.section
                  id="stock-assistant-panel"
                  className="stock-assistant-panel"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="stock-assistant-title"
                  initial={reduceMotion ? false : { opacity: 0, x: 48, scale: 0.985 }}
                  animate={{ opacity: 1, x: 0, scale: 1 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 40, scale: 0.985 }}
                  transition={reduceMotion ? { duration: 0 } : PANEL_TRANSITION}
                >
                  <div className="stock-assistant-panel__header">
                    <div className="stock-assistant-panel__identity">
                      <span className="stock-assistant-panel__mark" aria-hidden="true">
                        <MessageSquareQuote className="h-4 w-4" />
                      </span>
                      <div>
                        <span className="stock-assistant-panel__eyebrow">DSA COPILOT</span>
                        <h2 id="stock-assistant-title">{t('assistant.title')}</h2>
                      </div>
                    </div>
                    <div className="stock-assistant-panel__actions">
                      <Tooltip content={t('assistant.openFullPage')} side="bottom">
                        <button
                          type="button"
                          className="stock-assistant-icon-button"
                          aria-label={t('assistant.openFullPage')}
                          onClick={() => {
                            setIsOpen(false);
                            navigate('/chat');
                          }}
                        >
                          <ExternalLink className="h-4 w-4" />
                        </button>
                      </Tooltip>
                      <Tooltip content={t('assistant.close')} side="bottom">
                        <button
                          ref={closeRef}
                          type="button"
                          className="stock-assistant-icon-button"
                          aria-label={t('assistant.close')}
                          onClick={closeAssistant}
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </Tooltip>
                    </div>
                  </div>
                  <div className="stock-assistant-panel__body">
                    <Suspense fallback={(
                      <div className="stock-assistant-loading" role="status">
                        <span className="stock-assistant-loading__ring" aria-hidden="true" />
                        <span>{t('assistant.loading')}</span>
                      </div>
                    )}>
                      <ChatPage variant="assistant" />
                    </Suspense>
                  </div>
                </motion.section>
              </div>
            ) : null}
          </AnimatePresence>,
          document.body,
        )
        : null}
    </>
  );
};
