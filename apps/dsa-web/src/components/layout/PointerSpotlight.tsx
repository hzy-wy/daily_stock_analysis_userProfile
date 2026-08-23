import { useRef } from 'react';
import { useGSAP } from '@gsap/react';
import { gsap } from 'gsap';

gsap.registerPlugin(useGSAP);

type PointerConditions = {
  finePointer: boolean;
  reduceMotion: boolean;
};

/**
 * A large ambient spotlight, not a replacement cursor. It follows the pointer
 * outside React state and disappears for touch and reduced-motion users.
 */
export function PointerSpotlight() {
  const spotlightRef = useRef<HTMLDivElement>(null);

  useGSAP((_, contextSafe) => {
    const spotlight = spotlightRef.current;
    if (!spotlight) return;

    const media = gsap.matchMedia();

    media.add(
      {
        finePointer: '(pointer: fine)',
        reduceMotion: '(prefers-reduced-motion: reduce)',
      },
      (context) => {
        const { finePointer, reduceMotion } = context.conditions as PointerConditions;
        if (!finePointer || reduceMotion || !contextSafe) {
          gsap.set(spotlight, { autoAlpha: 0 });
          return;
        }

        gsap.set(spotlight, { xPercent: -50, yPercent: -50, autoAlpha: 0 });
        const moveX = gsap.quickTo(spotlight, 'x', { duration: 0.42, ease: 'power3.out' });
        const moveY = gsap.quickTo(spotlight, 'y', { duration: 0.42, ease: 'power3.out' });

        const handlePointerMove = contextSafe((event: PointerEvent) => {
          moveX(event.clientX);
          moveY(event.clientY);
          gsap.to(spotlight, { autoAlpha: 1, duration: 0.24, overwrite: 'auto' });
        });
        const handlePointerLeave = contextSafe(() => {
          gsap.to(spotlight, { autoAlpha: 0, duration: 0.32, overwrite: 'auto' });
        });

        window.addEventListener('pointermove', handlePointerMove, { passive: true });
        document.documentElement.addEventListener('mouseleave', handlePointerLeave);

        return () => {
          window.removeEventListener('pointermove', handlePointerMove);
          document.documentElement.removeEventListener('mouseleave', handlePointerLeave);
        };
      },
      spotlight,
    );

    return () => media.revert();
  }, { scope: spotlightRef });

  return <div ref={spotlightRef} className="app-pointer-spotlight" aria-hidden="true" />;
}
