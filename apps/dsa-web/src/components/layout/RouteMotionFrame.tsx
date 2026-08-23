import { useRef, type ReactNode } from 'react';
import { useGSAP } from '@gsap/react';
import { gsap } from 'gsap';

gsap.registerPlugin(useGSAP);

type RouteMotionFrameProps = {
  children: ReactNode;
};

type MotionConditions = {
  reduceMotion: boolean;
};

/**
 * Runs after a lazy route has resolved so page transitions never animate only
 * the loading fallback. Child staggering is intentionally capped to keep dense
 * dashboards responsive.
 */
export function RouteMotionFrame({ children }: RouteMotionFrameProps) {
  const frameRef = useRef<HTMLDivElement>(null);

  useGSAP(() => {
    const frame = frameRef.current;
    if (!frame) return;

    const media = gsap.matchMedia();

    media.add(
      { reduceMotion: '(prefers-reduced-motion: reduce)' },
      (context) => {
        const { reduceMotion } = context.conditions as MotionConditions;
        const pageRoot = frame.firstElementChild as HTMLElement | null;
        const revealItems = pageRoot
          ? Array.from(pageRoot.children)
            .filter((node): node is HTMLElement => node instanceof HTMLElement)
            .slice(0, 12)
          : [];

        const tracer = frame.querySelector<HTMLElement>('.route-motion-tracer');

        if (reduceMotion) {
          if (pageRoot) {
            gsap.fromTo(pageRoot, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.18, clearProps: 'opacity,visibility' });
          }
          return;
        }

        const timeline = gsap.timeline({ defaults: { ease: 'power3.out' } });
        if (tracer) {
          timeline.fromTo(
            tracer,
            { autoAlpha: 0, xPercent: -110 },
            { autoAlpha: 1, xPercent: 110, duration: 0.7, ease: 'power2.inOut', clearProps: 'opacity,visibility,transform' },
            0,
          );
        }

        if (pageRoot) {
          timeline.fromTo(
            pageRoot,
            { autoAlpha: 0, y: 16, scale: 0.995 },
            { autoAlpha: 1, y: 0, scale: 1, duration: 0.52, clearProps: 'opacity,visibility,transform' },
            0.08,
          );
        }

        if (revealItems.length > 1) {
          timeline.fromTo(
            revealItems,
            { autoAlpha: 0, y: 18 },
            {
              autoAlpha: 1,
              y: 0,
              duration: 0.44,
              stagger: 0.035,
              clearProps: 'opacity,visibility,transform',
            },
            0.16,
          );
        }
      },
      frame,
    );

    return () => media.revert();
  }, { scope: frameRef });

  return (
    <div ref={frameRef} className="route-motion-frame min-h-0 min-w-0">
      {children}
      <span className="route-motion-tracer" aria-hidden="true" />
    </div>
  );
}
