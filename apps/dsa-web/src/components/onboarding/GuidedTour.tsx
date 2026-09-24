import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ArrowLeft, ArrowRight, Check, MousePointer2, X } from 'lucide-react';
import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { UiLanguage } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { ONBOARDING_COMMON_COPY, type OnboardingStep } from './onboardingContent';
import type { OnboardingResult } from './onboardingState';
import './onboarding.css';

type HighlightRect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

type ViewportSize = {
  width: number;
  height: number;
};

type GuidedTourProps = {
  isOpen: boolean;
  language: UiLanguage;
  roleLabel: string;
  steps: OnboardingStep[];
  onClose: (result: OnboardingResult) => void;
  onStepChange?: (step: OnboardingStep, index: number) => void;
};

const SPOTLIGHT_GAP = 8;
const VIEWPORT_GAP = 16;
const CARD_TARGET_GAP = 18;
const CARD_MAX_WIDTH = 384;
const CARD_FALLBACK_HEIGHT = 330;
const TARGET_PROBE_FRAMES = 45;

function readViewport(): ViewportSize {
  if (typeof window === 'undefined') return { width: 1280, height: 800 };
  return { width: window.innerWidth, height: window.innerHeight };
}

function isVisibleElement(element: Element): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return rect.width > 0
    && rect.height > 0
    && style.display !== 'none'
    && style.visibility !== 'hidden';
}

function findVisibleTarget(selector?: string): HTMLElement | null {
  if (!selector || typeof document === 'undefined') return null;
  return Array.from(document.querySelectorAll(selector)).find(isVisibleElement) ?? null;
}

function readHighlightRect(target: HTMLElement | null): HighlightRect | null {
  if (!target) return null;
  const rect = target.getBoundingClientRect();
  const left = Math.max(0, rect.left - SPOTLIGHT_GAP);
  const top = Math.max(0, rect.top - SPOTLIGHT_GAP);
  const right = Math.min(window.innerWidth, rect.right + SPOTLIGHT_GAP);
  const bottom = Math.min(window.innerHeight, rect.bottom + SPOTLIGHT_GAP);
  return {
    top,
    left,
    right,
    bottom,
    width: Math.max(0, right - left),
    height: Math.max(0, bottom - top),
  };
}

function equalRect(left: HighlightRect | null, right: HighlightRect | null): boolean {
  if (left === right) return true;
  if (!left || !right) return false;
  return Math.abs(left.top - right.top) < 1
    && Math.abs(left.left - right.left) < 1
    && Math.abs(left.width - right.width) < 1
    && Math.abs(left.height - right.height) < 1;
}

function isOutsideComfortableViewport(target: HTMLElement): boolean {
  const rect = target.getBoundingClientRect();
  const topSafeArea = 92;
  return rect.top < topSafeArea
    || rect.bottom > window.innerHeight - VIEWPORT_GAP
    || rect.left < VIEWPORT_GAP
    || rect.right > window.innerWidth - VIEWPORT_GAP;
}

function formatProgress(template: string, current: number, total: number): string {
  return template
    .replace('{current}', String(current))
    .replace('{total}', String(total));
}

export const GuidedTour: React.FC<GuidedTourProps> = ({
  isOpen,
  language,
  roleLabel,
  steps,
  onClose,
  onStepChange,
}) => {
  const reduceMotion = useReducedMotion();
  const [activeIndex, setActiveIndex] = useState(0);
  const [targetRect, setTargetRect] = useState<HighlightRect | null>(null);
  const [targetFound, setTargetFound] = useState(true);
  const [viewport, setViewport] = useState<ViewportSize>(readViewport);
  const [cardHeight, setCardHeight] = useState(CARD_FALLBACK_HEIGHT);
  const cardRef = useRef<HTMLElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const activeIndexRef = useRef(0);
  const copy = ONBOARDING_COMMON_COPY[language];
  const step = steps[activeIndex];
  const isLastStep = activeIndex === steps.length - 1;

  useEffect(() => {
    activeIndexRef.current = activeIndex;
  }, [activeIndex]);

  const finish = useCallback((result: OnboardingResult) => {
    setActiveIndex(0);
    setTargetRect(null);
    onClose(result);
  }, [onClose]);

  const activateStep = useCallback((nextIndex: number) => {
    const boundedIndex = Math.max(0, Math.min(nextIndex, steps.length - 1));
    const nextStep = steps[boundedIndex];
    const nextTarget = findVisibleTarget(nextStep?.target);

    // Commit the new step and its best-known target in the same input turn.
    // Route-backed targets center the card while their lazy page mounts instead
    // of leaving the previous spotlight on screen.
    setTargetFound(!nextStep?.target || Boolean(nextTarget));
    setTargetRect(readHighlightRect(nextTarget));
    setActiveIndex(boundedIndex);
  }, [steps]);

  const goNext = useCallback(() => {
    if (isLastStep) {
      finish('completed');
      return;
    }
    activateStep(activeIndexRef.current + 1);
  }, [activateStep, finish, isLastStep]);

  const goPrevious = useCallback(() => {
    activateStep(activeIndexRef.current - 1);
  }, [activateStep]);

  useEffect(() => {
    if (!isOpen) return undefined;

    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    queueMicrotask(() => cardRef.current?.focus({ preventScroll: true }));

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        finish('skipped');
      } else if (event.key === 'ArrowLeft' && activeIndexRef.current > 0) {
        goPrevious();
      } else if (event.key === 'ArrowRight') {
        goNext();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocusRef.current?.focus({ preventScroll: true });
    };
  }, [finish, goNext, goPrevious, isOpen]);

  useEffect(() => {
    if (!isOpen || !step) return undefined;
    onStepChange?.(step, activeIndex);

    let frame = 0;
    let probeCount = 0;
    let observedTarget: HTMLElement | null = null;
    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(() => scheduleUpdate());

    const updateTarget = (allowScroll = false) => {
      const target = findVisibleTarget(step.target);
      if (target !== observedTarget) {
        if (observedTarget) resizeObserver?.unobserve(observedTarget);
        observedTarget = target;
        if (target) resizeObserver?.observe(target);
      }

      if (target && allowScroll && isOutsideComfortableViewport(target)) {
        target.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'nearest' });
      }

      const nextRect = readHighlightRect(target);
      setTargetFound(!step.target || Boolean(target));
      setTargetRect((current) => equalRect(current, nextRect) ? current : nextRect);
      return Boolean(target) || !step.target;
    };

    function scheduleUpdate() {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => updateTarget(false));
    }

    const probeTarget = () => {
      const found = updateTarget(probeCount === 0);
      probeCount += 1;
      if (!found && probeCount < TARGET_PROBE_FRAMES) {
        frame = window.requestAnimationFrame(probeTarget);
      }
    };

    frame = window.requestAnimationFrame(probeTarget);
    const handleResize = () => {
      setViewport(readViewport());
      scheduleUpdate();
    };
    window.addEventListener('resize', handleResize, { passive: true });
    window.addEventListener('scroll', scheduleUpdate, true);
    const observer = new MutationObserver(scheduleUpdate);
    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      resizeObserver?.disconnect();
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('scroll', scheduleUpdate, true);
    };
  }, [activeIndex, isOpen, onStepChange, step]);

  useEffect(() => {
    if (!isOpen || !step?.advanceOnTargetClick || !step.target) return undefined;

    const handleTargetClick = (event: MouseEvent) => {
      const target = findVisibleTarget(step.target);
      if (target?.contains(event.target as Node)) {
        queueMicrotask(goNext);
      }
    };
    document.addEventListener('click', handleTargetClick, true);
    return () => document.removeEventListener('click', handleTargetClick, true);
  }, [goNext, isOpen, step]);

  useEffect(() => {
    const card = cardRef.current;
    if (!card || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const nextHeight = entry?.borderBoxSize?.[0]?.blockSize ?? entry?.contentRect.height;
      if (nextHeight > 0) setCardHeight(nextHeight);
    });
    observer.observe(card);
    return () => observer.disconnect();
  }, [isOpen]);

  const cardPosition = useMemo(() => {
    const cardWidth = Math.min(CARD_MAX_WIDTH, viewport.width - VIEWPORT_GAP * 2);
    const measuredHeight = Math.min(cardHeight, viewport.height - VIEWPORT_GAP * 2);
    if (!targetRect) {
      return {
        x: Math.max(VIEWPORT_GAP, (viewport.width - cardWidth) / 2),
        y: Math.max(VIEWPORT_GAP, (viewport.height - measuredHeight) / 2),
      };
    }

    const roomRight = viewport.width - targetRect.right;
    const roomLeft = targetRect.left;
    const roomBelow = viewport.height - targetRect.bottom;
    const clampX = (value: number) => Math.max(
      VIEWPORT_GAP,
      Math.min(value, viewport.width - cardWidth - VIEWPORT_GAP),
    );
    const clampY = (value: number) => Math.max(
      VIEWPORT_GAP,
      Math.min(value, viewport.height - measuredHeight - VIEWPORT_GAP),
    );

    if (roomRight >= cardWidth + CARD_TARGET_GAP + VIEWPORT_GAP) {
      return {
        x: targetRect.right + CARD_TARGET_GAP,
        y: clampY(targetRect.top + targetRect.height / 2 - measuredHeight / 2),
      };
    }
    if (roomLeft >= cardWidth + CARD_TARGET_GAP + VIEWPORT_GAP) {
      return {
        x: targetRect.left - cardWidth - CARD_TARGET_GAP,
        y: clampY(targetRect.top + targetRect.height / 2 - measuredHeight / 2),
      };
    }
    if (roomBelow >= measuredHeight + CARD_TARGET_GAP + VIEWPORT_GAP) {
      return {
        x: clampX(targetRect.left + targetRect.width / 2 - cardWidth / 2),
        y: targetRect.bottom + CARD_TARGET_GAP,
      };
    }
    return {
      x: clampX(targetRect.left + targetRect.width / 2 - cardWidth / 2),
      y: clampY(targetRect.top - measuredHeight - CARD_TARGET_GAP),
    };
  }, [cardHeight, targetRect, viewport]);

  const progressLabel = useMemo(
    () => formatProgress(copy.progress, activeIndex + 1, steps.length),
    [activeIndex, copy.progress, steps.length],
  );

  if (!step) return null;

  return (
    <AnimatePresence>
      {isOpen ? (
        <div className="onboarding-tour" data-testid="guided-tour">
          {targetRect ? (
            <>
              <div className="onboarding-tour__mask" style={{ inset: '0 0 auto 0', height: targetRect.top }} />
              <div className="onboarding-tour__mask" style={{ top: targetRect.top, left: 0, width: targetRect.left, height: targetRect.height }} />
              <div className="onboarding-tour__mask" style={{ top: targetRect.top, left: targetRect.right, right: 0, height: targetRect.height }} />
              <div className="onboarding-tour__mask" style={{ top: targetRect.bottom, right: 0, bottom: 0, left: 0 }} />
              <motion.div
                className="onboarding-tour__spotlight"
                aria-hidden="true"
                initial={false}
                animate={{
                  x: targetRect.left,
                  y: targetRect.top,
                  width: targetRect.width,
                  height: targetRect.height,
                }}
                transition={reduceMotion ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.22 }}
              />
            </>
          ) : (
            <div className="onboarding-tour__mask onboarding-tour__mask--full" />
          )}

          <motion.section
            ref={cardRef}
            tabIndex={-1}
            role="dialog"
            aria-labelledby="onboarding-tour-title"
            aria-describedby="onboarding-tour-description"
            className={cn('onboarding-tour__card', !targetRect && 'onboarding-tour__card--centered')}
            initial={reduceMotion ? false : { opacity: 0, scale: 0.985, ...cardPosition }}
            animate={{ opacity: 1, scale: 1, ...cardPosition }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.99 }}
            transition={reduceMotion ? { duration: 0 } : { type: 'spring', bounce: 0, duration: 0.26 }}
          >
            <div className="onboarding-tour__topline">
              <span className="onboarding-tour__role">{roleLabel}</span>
              <button
                type="button"
                className="onboarding-tour__close"
                onClick={() => finish('skipped')}
                aria-label={copy.skip}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div
              className="onboarding-tour__progress"
              aria-label={progressLabel}
              style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}
            >
              {steps.map((item, index) => (
                <span
                  key={item.id}
                  className={cn(
                    'onboarding-tour__progress-segment',
                    index <= activeIndex && 'onboarding-tour__progress-segment--active',
                  )}
                />
              ))}
            </div>

            <div key={step.id} className="onboarding-tour__content" aria-live="polite">
              <p className="onboarding-tour__eyebrow">{step.eyebrow}</p>
              <h2 id="onboarding-tour-title" className="onboarding-tour__title">{step.title}</h2>
              <p id="onboarding-tour-description" className="onboarding-tour__description">{step.description}</p>

              {step.interactionHint && targetFound ? (
                <div className="onboarding-tour__interaction" role="status">
                  <MousePointer2 className="h-4 w-4" />
                  <span>{step.interactionHint}</span>
                </div>
              ) : null}
              {step.target && !targetFound ? (
                <p className="onboarding-tour__unavailable">{copy.targetUnavailable}</p>
              ) : null}
            </div>

            <footer className="onboarding-tour__footer">
              <button type="button" className="onboarding-tour__skip" onClick={() => finish('skipped')}>
                {copy.skip}
              </button>
              <div className="onboarding-tour__actions">
                {activeIndex > 0 ? (
                  <button
                    type="button"
                    className="onboarding-tour__button onboarding-tour__button--secondary"
                    onClick={goPrevious}
                  >
                    <ArrowLeft className="h-4 w-4" />
                    {copy.previous}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="onboarding-tour__button onboarding-tour__button--primary"
                  onClick={goNext}
                >
                  {isLastStep ? <Check className="h-4 w-4" /> : null}
                  {isLastStep ? copy.finish : copy.next}
                  {!isLastStep ? <ArrowRight className="h-4 w-4" /> : null}
                </button>
              </div>
            </footer>
          </motion.section>
        </div>
      ) : null}
    </AnimatePresence>
  );
};

export default GuidedTour;
