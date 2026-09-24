import { useEffect, useRef } from 'react';

type Candle = {
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
};

type PointerState = {
  x: number;
  y: number;
  targetX: number;
  targetY: number;
  active: boolean;
};

type MarketPoint = {
  x: number;
  y: number;
  price: number;
  seriesIndex: number;
};

const FRAME_INTERVAL = 1000 / 30;
const MAX_DEVICE_PIXEL_RATIO = 1.5;
const MARKET_SERIES_LENGTH = 720;
const CANDLE_SPACING = 22;
const CANDLE_WIDTH = 7;
const CANDLE_SCROLL_SPEED = 3.9 / 1000;
const TRAIL_ROUND_TRIP = 36_000;
const SCAN_ROUND_TRIP = 54_000;
const UP_COLOR = '248, 92, 105';
const DOWN_COLOR = '43, 200, 141';
const ACCENT_COLOR = '25, 195, 230';
const SECONDARY_LINE_COLOR = '114, 146, 181';
const MONO_FONT = 'ui-monospace, SFMono-Regular, Menlo, monospace';

function createSeededRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0;
    return value / 4294967296;
  };
}

function createMarketSeries(count: number): Candle[] {
  const random = createSeededRandom(20260827);
  let previousClose = 100;

  return Array.from({ length: count }, (_, index) => {
    const cycle = Math.sin(index * 0.31) * 0.72 + Math.sin(index * 0.083) * 0.46;
    const meanReversion = (100 - previousClose) * 0.014;
    const drift = 0.025 + meanReversion + cycle * 0.12 + (random() - 0.49) * 1.35;
    const open = previousClose + (random() - 0.5) * 0.75;
    const close = Math.max(82, open + drift);
    const wick = 0.28 + random() * 0.95;
    const high = Math.max(open, close) + wick;
    const low = Math.min(open, close) - wick * (0.6 + random() * 0.4);
    const volume = 0.26 + random() * 0.66 + Math.abs(close - open) * 0.22;
    previousClose = close;
    return { open, close, high, low, volume };
  });
}

function movingAverage(candles: Candle[], index: number, windowSize: number): number {
  const start = Math.max(0, index - windowSize + 1);
  let sum = 0;
  for (let cursor = start; cursor <= index; cursor += 1) sum += candles[cursor].close;
  return sum / (index - start + 1);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function pingPongProgress(time: number, roundTrip: number): number {
  return (1 - Math.cos((time / roundTrip) * Math.PI * 2)) / 2;
}

export const ParticleBackground = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    // jsdom exposes the canvas element but intentionally has no 2D renderer.
    if (navigator.userAgent.includes('jsdom')) return undefined;
    const context = canvas.getContext('2d');
    if (!context) return undefined;

    const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const pointer: PointerState = {
      x: window.innerWidth * 0.42,
      y: window.innerHeight * 0.48,
      targetX: window.innerWidth * 0.42,
      targetY: window.innerHeight * 0.48,
      active: false,
    };
    let width = 0;
    let height = 0;
    let candles: Candle[] = [];
    let fastAverages: number[] = [];
    let slowAverages: number[] = [];
    let displayedMinPrice = 0;
    let displayedMaxPrice = 0;
    let animationFrame = 0;
    let lastFrameAt = 0;
    let lastAnimationAt = 0;
    let sceneElapsed = 0;
    let reducedMotion = reducedMotionQuery.matches;

    const priceToY = (price: number, minPrice: number, maxPrice: number) => {
      const plotTop = height * 0.16;
      const plotHeight = height * 0.58;
      const ratio = (price - minPrice) / Math.max(1, maxPrice - minPrice);
      return plotTop + plotHeight - ratio * plotHeight;
    };

    const drawGrid = () => {
      context.save();
      const gridSize = 44;
      for (let x = 0, column = 0; x <= width; x += gridSize, column += 1) {
        context.strokeStyle = column % 4 === 0
          ? 'rgba(112, 153, 181, 0.075)'
          : 'rgba(112, 153, 181, 0.038)';
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(x, 0);
        context.lineTo(x, height);
        context.stroke();
      }
      for (let y = height * 0.16, row = 0; y <= height * 0.84; y += gridSize, row += 1) {
        context.strokeStyle = row % 4 === 0
          ? 'rgba(112, 153, 181, 0.075)'
          : 'rgba(112, 153, 181, 0.038)';
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(width, y);
        context.stroke();
      }
      context.restore();
    };

    const drawDataPipeline = (time: number) => {
      const stages = ['MARKET FEED', 'FACTOR FUSION', 'RISK CHECK', 'AI SIGNAL'];
      const railStart = Math.max(28, width * 0.035);
      const railEnd = Math.min(width * 0.64, railStart + 760);
      const railY = Math.max(58, height * 0.075);
      const segmentWidth = (railEnd - railStart) / (stages.length - 1);

      context.save();
      context.strokeStyle = `rgba(${ACCENT_COLOR}, 0.1)`;
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(railStart, railY);
      context.lineTo(railEnd, railY);
      context.stroke();
      context.font = `600 9px ${MONO_FONT}`;
      stages.forEach((stage, index) => {
        const x = railStart + segmentWidth * index;
        const pulse = reducedMotion ? 0.45 : 0.35 + Math.sin(time * 0.00075 - index * 0.85) * 0.12;
        context.fillStyle = `rgba(${ACCENT_COLOR}, ${pulse})`;
        context.beginPath();
        context.arc(x, railY, index === stages.length - 1 ? 2.8 : 2, 0, Math.PI * 2);
        context.fill();
        context.fillStyle = `rgba(155, 183, 202, ${0.3 + index * 0.035})`;
        context.fillText(stage, x - (index === 0 ? 0 : 28), railY - 13);
      });
      context.restore();
    };

    const drawPriceLevels = (minPrice: number, maxPrice: number) => {
      const plotTop = height * 0.16;
      const plotHeight = height * 0.58;
      const railEnd = width * 0.69;
      context.save();
      context.setLineDash([2, 7]);
      context.font = `500 9px ${MONO_FONT}`;
      [0.2, 0.5, 0.8].forEach((ratio) => {
        const y = plotTop + plotHeight * ratio;
        const price = maxPrice - (maxPrice - minPrice) * ratio;
        context.strokeStyle = 'rgba(129, 162, 186, 0.055)';
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(railEnd, y);
        context.stroke();
        context.fillStyle = 'rgba(152, 178, 196, 0.2)';
        context.fillText(price.toFixed(1), railEnd - 32, y - 5);
      });
      context.restore();
    };

    const drawAnalysisSweep = (time: number) => {
      if (reducedMotion) return;
      const progress = pingPongProgress(time, SCAN_ROUND_TRIP);
      const x = width * (0.08 + progress * 0.57);
      const sweep = context.createLinearGradient(x - 120, 0, x + 120, 0);
      sweep.addColorStop(0, `rgba(${ACCENT_COLOR}, 0)`);
      sweep.addColorStop(0.5, `rgba(${ACCENT_COLOR}, 0.035)`);
      sweep.addColorStop(1, `rgba(${ACCENT_COLOR}, 0)`);
      context.save();
      context.fillStyle = sweep;
      context.fillRect(x - 120, height * 0.12, 240, height * 0.72);
      context.setLineDash([3, 8]);
      context.strokeStyle = `rgba(${ACCENT_COLOR}, 0.13)`;
      context.beginPath();
      context.moveTo(x, height * 0.13);
      context.lineTo(x, height * 0.84);
      context.stroke();
      context.setLineDash([]);
      context.fillStyle = `rgba(${ACCENT_COLOR}, 0.34)`;
      context.font = `600 9px ${MONO_FONT}`;
      context.fillText('DSA SCAN', x + 8, height * 0.15);
      context.restore();
    };

    const drawSignalMarker = (
      pointX: number,
      pointY: number,
      seriesIndex: number,
      time: number,
      label: string,
    ) => {
      const pulse = reducedMotion ? 0.42 : 0.32 + Math.sin(time * 0.0012 + seriesIndex) * 0.1;
      context.save();
      context.translate(pointX, pointY);
      context.rotate(Math.PI / 4);
      context.strokeStyle = `rgba(${ACCENT_COLOR}, ${pulse})`;
      context.lineWidth = 1;
      context.strokeRect(-3.5, -3.5, 7, 7);
      context.restore();
      context.fillStyle = `rgba(${ACCENT_COLOR}, ${pulse + 0.06})`;
      context.font = `600 8px ${MONO_FONT}`;
      context.fillText(label, pointX + 9, pointY + 3);
    };

    const drawMovingAverage = (
      points: MarketPoint[],
      color: string,
      alpha: number,
      lineWidth: number,
    ) => {
      if (points.length < 2) return;
      const gradient = context.createLinearGradient(0, 0, width, 0);
      gradient.addColorStop(0, `rgba(${color}, 0)`);
      gradient.addColorStop(0.18, `rgba(${color}, ${alpha * 0.58})`);
      gradient.addColorStop(0.76, `rgba(${color}, ${alpha})`);
      gradient.addColorStop(1, `rgba(${color}, 0.02)`);
      context.strokeStyle = gradient;
      context.lineWidth = lineWidth;
      context.beginPath();
      points.forEach((point, index) => {
        if (index === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
      });
      context.stroke();
    };

    const drawPredictionRange = (points: MarketPoint[], time: number) => {
      if (points.length < 8) return;
      const anchorIndex = Math.floor(points.length * 0.62);
      const anchor = points[anchorIndex];
      if (!anchor) return;
      const rangeWidth = Math.min(150, width * 0.09);
      const verticalBias = Math.sin(time * 0.00022) * 5;
      const range = context.createLinearGradient(anchor.x, 0, anchor.x + rangeWidth, 0);
      range.addColorStop(0, `rgba(${ACCENT_COLOR}, 0.075)`);
      range.addColorStop(1, `rgba(${ACCENT_COLOR}, 0)`);

      context.save();
      context.fillStyle = range;
      context.beginPath();
      context.moveTo(anchor.x, anchor.y);
      context.lineTo(anchor.x + rangeWidth, anchor.y - 20 + verticalBias);
      context.lineTo(anchor.x + rangeWidth, anchor.y + 24 + verticalBias);
      context.closePath();
      context.fill();
      context.setLineDash([3, 5]);
      context.strokeStyle = `rgba(${ACCENT_COLOR}, 0.2)`;
      context.beginPath();
      context.moveTo(anchor.x, anchor.y);
      context.bezierCurveTo(
        anchor.x + rangeWidth * 0.35,
        anchor.y - 7,
        anchor.x + rangeWidth * 0.7,
        anchor.y + verticalBias,
        anchor.x + rangeWidth,
        anchor.y - 4 + verticalBias,
      );
      context.stroke();
      context.setLineDash([]);
      context.fillStyle = `rgba(${ACCENT_COLOR}, 0.35)`;
      context.font = `600 8px ${MONO_FONT}`;
      context.fillText('AI RANGE', anchor.x + rangeWidth * 0.52, anchor.y - 24 + verticalBias);
      context.restore();
    };

    const drawMarketLabels = (time: number) => {
      const labels = [
        { code: 'CN · SSE', value: '3,218.42', delta: '+0.62%', color: UP_COLOR },
        { code: 'HK · HSI', value: '24,986.13', delta: '-0.18%', color: DOWN_COLOR },
        { code: 'US · SPX', value: '6,481.07', delta: '+0.34%', color: UP_COLOR },
        { code: 'BREADTH', value: '64.8%', delta: 'ADV', color: ACCENT_COLOR },
        { code: 'VOL RATIO', value: '1.24', delta: 'ACTIVE', color: ACCENT_COLOR },
        { code: 'AI CONF', value: '78 / 100', delta: 'WATCH', color: ACCENT_COLOR },
      ];
      const visibleLabels = width < 820 ? labels.slice(0, 3) : labels;
      const railWidth = Math.min(width * 0.69, 1080);
      const cellWidth = railWidth / visibleLabels.length;
      const pulse = reducedMotion ? 0.7 : 0.64 + Math.sin(time * 0.0012) * 0.06;
      context.save();
      context.font = `500 10px ${MONO_FONT}`;
      visibleLabels.forEach((label, index) => {
        const x = 28 + index * cellWidth;
        const y = height - 30;
        context.fillStyle = 'rgba(151, 174, 196, 0.38)';
        context.fillText(label.code, x, y);
        context.fillStyle = `rgba(${label.color}, ${pulse})`;
        context.fillText(`${label.value}  ${label.delta}`, x, y + 14);
      });
      context.restore();
    };

    const drawScene = (time: number) => {
      context.clearRect(0, 0, width, height);
      drawGrid();
      drawDataPipeline(time);
      if (candles.length === 0) return;

      const visibleCount = Math.ceil(width / CANDLE_SPACING) + 6;
      const scrollPixels = reducedMotion ? 0 : time * CANDLE_SCROLL_SPEED;
      const advancedCandles = Math.floor(scrollPixels / CANDLE_SPACING);
      const availableTravel = Math.max(1, candles.length - visibleCount - 2);
      const firstSeriesIndex = advancedCandles % availableTravel;
      const fractionalOffset = scrollPixels % CANDLE_SPACING;
      const visibleEntries = Array.from({ length: visibleCount }, (_, slot) => {
        const seriesIndex = firstSeriesIndex + slot;
        return {
          candle: candles[seriesIndex],
          seriesIndex,
          x: -CANDLE_SPACING * 2 - fractionalOffset + slot * CANDLE_SPACING,
        };
      }).filter((entry) => entry.candle);

      const targetMin = Math.min(...visibleEntries.map((entry) => entry.candle.low));
      const targetMax = Math.max(...visibleEntries.map((entry) => entry.candle.high));
      const pricePadding = Math.max(0.6, (targetMax - targetMin) * 0.08);
      const paddedMin = targetMin - pricePadding;
      const paddedMax = targetMax + pricePadding;
      if (!displayedMinPrice || !displayedMaxPrice || reducedMotion) {
        displayedMinPrice = paddedMin;
        displayedMaxPrice = paddedMax;
      } else {
        displayedMinPrice += (paddedMin - displayedMinPrice) * 0.045;
        displayedMaxPrice += (paddedMax - displayedMaxPrice) * 0.045;
      }

      drawPriceLevels(displayedMinPrice, displayedMaxPrice);
      drawAnalysisSweep(time);

      const volumeTop = height * 0.77;
      const volumeHeight = height * 0.11;
      const fastPoints: MarketPoint[] = [];
      const slowPoints: MarketPoint[] = [];

      context.save();
      visibleEntries.forEach(({ candle, seriesIndex, x }) => {
        if (x < -CANDLE_SPACING || x > width + CANDLE_SPACING) return;
        const rising = candle.close >= candle.open;
        const color = rising ? UP_COLOR : DOWN_COLOR;
        const openY = priceToY(candle.open, displayedMinPrice, displayedMaxPrice);
        const closeY = priceToY(candle.close, displayedMinPrice, displayedMaxPrice);
        const highY = priceToY(candle.high, displayedMinPrice, displayedMaxPrice);
        const lowY = priceToY(candle.low, displayedMinPrice, displayedMaxPrice);
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.max(1.5, Math.abs(closeY - openY));

        context.strokeStyle = `rgba(${color}, 0.3)`;
        context.fillStyle = `rgba(${color}, 0.17)`;
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(x, highY);
        context.lineTo(x, lowY);
        context.stroke();
        context.fillRect(x - CANDLE_WIDTH / 2, bodyTop, CANDLE_WIDTH, bodyHeight);

        context.fillStyle = `rgba(${color}, ${0.04 + candle.volume * 0.052})`;
        context.fillRect(
          x - CANDLE_WIDTH / 2,
          volumeTop + (1 - candle.volume) * volumeHeight,
          CANDLE_WIDTH,
          candle.volume * volumeHeight,
        );

        fastPoints.push({
          x,
          y: priceToY(fastAverages[seriesIndex], displayedMinPrice, displayedMaxPrice),
          price: fastAverages[seriesIndex],
          seriesIndex,
        });
        slowPoints.push({
          x,
          y: priceToY(slowAverages[seriesIndex], displayedMinPrice, displayedMaxPrice),
          price: slowAverages[seriesIndex],
          seriesIndex,
        });

        if (seriesIndex % 43 === 11) drawSignalMarker(x, highY - 13, seriesIndex, time, 'NEWS');
        if (seriesIndex % 61 === 27) drawSignalMarker(x, lowY + 15, seriesIndex, time, 'AI 78');
      });

      drawMovingAverage(slowPoints, SECONDARY_LINE_COLOR, 0.2, 1);
      drawMovingAverage(fastPoints, ACCENT_COLOR, 0.38, 1.4);
      drawPredictionRange(fastPoints, time);

      if (fastPoints.length > 1) {
        const trailProgress = reducedMotion ? 0.62 : pingPongProgress(time, TRAIL_ROUND_TRIP);
        const pulseIndex = Math.round(trailProgress * (fastPoints.length - 1));
        const pulsePoint = fastPoints[pulseIndex];
        if (pulsePoint) {
          const glow = context.createRadialGradient(pulsePoint.x, pulsePoint.y, 0, pulsePoint.x, pulsePoint.y, 18);
          glow.addColorStop(0, `rgba(${ACCENT_COLOR}, 0.78)`);
          glow.addColorStop(0.28, `rgba(${ACCENT_COLOR}, 0.28)`);
          glow.addColorStop(1, `rgba(${ACCENT_COLOR}, 0)`);
          context.fillStyle = glow;
          context.beginPath();
          context.arc(pulsePoint.x, pulsePoint.y, 18, 0, Math.PI * 2);
          context.fill();
          context.fillStyle = `rgba(${ACCENT_COLOR}, 0.92)`;
          context.beginPath();
          context.arc(pulsePoint.x, pulsePoint.y, 2, 0, Math.PI * 2);
          context.fill();
        }

        if (pointer.active && !reducedMotion) {
          pointer.x += (pointer.targetX - pointer.x) * 0.22;
          pointer.y += (pointer.targetY - pointer.y) * 0.22;
          const nearest = fastPoints.reduce((best, point) => (
            Math.abs(point.x - pointer.x) < Math.abs(best.x - pointer.x) ? point : best
          ));
          const crosshairAlpha = pointer.x < width * 0.72 ? 0.32 : 0.16;
          context.setLineDash([3, 5]);
          context.strokeStyle = `rgba(${ACCENT_COLOR}, ${crosshairAlpha})`;
          context.lineWidth = 1;
          context.beginPath();
          context.moveTo(nearest.x, height * 0.13);
          context.lineTo(nearest.x, height * 0.88);
          context.stroke();
          context.setLineDash([]);
          context.fillStyle = `rgba(${ACCENT_COLOR}, 0.88)`;
          context.beginPath();
          context.arc(nearest.x, nearest.y, 3, 0, Math.PI * 2);
          context.fill();

          const labelX = clamp(nearest.x + 10, 12, width - 106);
          const labelY = clamp(nearest.y - 28, 18, height - 44);
          context.fillStyle = 'rgba(5, 18, 31, 0.82)';
          context.fillRect(labelX, labelY, 96, 34);
          context.fillStyle = `rgba(${ACCENT_COLOR}, 0.9)`;
          context.font = `600 10px ${MONO_FONT}`;
          context.fillText('MA8 · SIGNAL', labelX + 8, labelY + 13);
          context.fillStyle = 'rgba(225, 238, 247, 0.74)';
          context.fillText(nearest.price.toFixed(2), labelX + 8, labelY + 27);
        }
      }

      drawMarketLabels(time);
      context.restore();
    };

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(bounds.width || window.innerWidth));
      height = Math.max(1, Math.round(bounds.height || window.innerHeight));
      const pixelRatio = Math.min(window.devicePixelRatio || 1, MAX_DEVICE_PIXEL_RATIO);
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      candles = createMarketSeries(Math.max(MARKET_SERIES_LENGTH, Math.ceil(width / CANDLE_SPACING) + 12));
      fastAverages = candles.map((_, index) => movingAverage(candles, index, 8));
      slowAverages = candles.map((_, index) => movingAverage(candles, index, 21));
      displayedMinPrice = 0;
      displayedMaxPrice = 0;
      pointer.x = width * 0.42;
      pointer.y = height * 0.48;
      pointer.targetX = pointer.x;
      pointer.targetY = pointer.y;
      drawScene(sceneElapsed);
    };

    const animate = (time: number) => {
      animationFrame = 0;
      if (document.hidden || reducedMotion) return;
      if (!lastAnimationAt) lastAnimationAt = time;
      sceneElapsed += Math.min(time - lastAnimationAt, 100);
      lastAnimationAt = time;
      if (time - lastFrameAt >= FRAME_INTERVAL) {
        lastFrameAt = time;
        drawScene(sceneElapsed);
      }
      animationFrame = window.requestAnimationFrame(animate);
    };

    const startAnimation = () => {
      if (!animationFrame && !document.hidden && !reducedMotion) {
        lastAnimationAt = 0;
        animationFrame = window.requestAnimationFrame(animate);
      }
    };

    const stopAnimation = () => {
      if (animationFrame) window.cancelAnimationFrame(animationFrame);
      animationFrame = 0;
      lastAnimationAt = 0;
    };

    const handlePointerMove = (event: PointerEvent) => {
      pointer.targetX = event.clientX;
      pointer.targetY = event.clientY;
      pointer.active = event.pointerType !== 'touch';
    };
    const handlePointerLeave = (event: PointerEvent) => {
      if (!event.relatedTarget) pointer.active = false;
    };
    const handleVisibilityChange = () => {
      if (document.hidden) stopAnimation();
      else startAnimation();
    };
    const handleMotionPreference = (event: MediaQueryListEvent) => {
      reducedMotion = event.matches;
      if (reducedMotion) {
        stopAnimation();
        drawScene(sceneElapsed);
      } else {
        startAnimation();
      }
    };

    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(resize);
    resizeObserver?.observe(canvas);
    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('pointermove', handlePointerMove, { passive: true });
    window.addEventListener('pointerout', handlePointerLeave, { passive: true });
    document.addEventListener('visibilitychange', handleVisibilityChange);
    reducedMotionQuery.addEventListener('change', handleMotionPreference);

    resize();
    startAnimation();

    return () => {
      stopAnimation();
      resizeObserver?.disconnect();
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerout', handlePointerLeave);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      reducedMotionQuery.removeEventListener('change', handleMotionPreference);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="login-market-canvas absolute inset-0 z-0 h-full w-full pointer-events-none"
      aria-hidden="true"
    />
  );
};
