import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { RotateCw, TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { OfficeEngine, type HoverState, type SceneLabels, type SceneState } from './OfficeEngine';
import type { AgentZone } from './officePlan';

export interface ObservatoryHandle {
  zoom: (direction: number) => void;
  rotate: () => void;
  reset: () => void;
  focusZone: (zone: AgentZone) => void;
  focusWorkPod: (index: number) => void;
  focusAgent: (id: string) => void;
}

interface Props {
  state: SceneState;
  labels: SceneLabels;
  onSelect: (id: string) => void;
  onOpenPatron: () => void;
  /** The hover card for an agent, drawn by the page from the same assignment as the modal. */
  renderHover: (id: string) => ReactNode;
}

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

/**
 * The canvas of the observatory. One engine per mount: the page keys this component by
 * workspace and floor-plan shape, so switching either disposes the old scene before the new
 * one is built and the page never holds two canvases (DESIGN §8).
 */
const ObservatoryScene = forwardRef<ObservatoryHandle, Props>(function ObservatoryScene(
  { state, labels, onSelect, onOpenPatron, renderHover },
  ref,
) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<OfficeEngine | null>(null);
  // The engine reads the latest props every frame without being rebuilt.
  const latest = useRef({ state, onSelect, onOpenPatron });
  const labelsAtMount = useRef(labels);
  const [supported] = useState(webglAvailable);
  const [failed, setFailed] = useState(false);
  const [hover, setHover] = useState<HoverState>(null);

  useLayoutEffect(() => {
    latest.current = { state, onSelect, onOpenPatron };
  });

  useImperativeHandle(ref, () => ({
    zoom: (direction) => engine.current?.zoom(direction),
    rotate: () => engine.current?.rotate(),
    reset: () => engine.current?.reset(),
    focusZone: (zone) => engine.current?.focusZone(zone),
    focusWorkPod: (index) => engine.current?.focusWorkPod(index),
    focusAgent: (id) => engine.current?.focusAgent(id),
  }), []);

  useEffect(() => {
    const element = host.current;
    if (!element || !supported) return;
    let instance: OfficeEngine | null = null;
    try {
      instance = new OfficeEngine(element, () => latest.current.state, labelsAtMount.current, {
        onSelect: (id) => latest.current.onSelect(id),
        onOpenPatron: () => latest.current.onOpenPatron(),
        onHover: setHover,
      });
      engine.current = instance;
    } catch (cause) {
      console.warn('Observatory: WebGL scene could not start', cause);
      // Deferred so the fallback renders on the next commit rather than inside this effect.
      queueMicrotask(() => setFailed(true));
    }
    return () => {
      instance?.dispose();
      engine.current = null;
    };
  }, [supported]);

  const hovered = hover && state.agents.some((agent) => agent.id === hover.id) ? hover : null;

  return (
    <div ref={host} className="absolute inset-0">
      {(!supported || failed) && (
        <div className="absolute inset-0 z-[5] flex flex-col items-center justify-center gap-3.5 bg-canvas-deep px-6 text-center text-ink-light">
          <TriangleAlert className="h-8 w-8 text-gold" strokeWidth={1.5} aria-hidden />
          <strong className="font-display text-[24px] font-normal text-ink-strong">{t('observatory.webgl.title')}</strong>
          <p className="max-w-[320px] text-body-sm">{t('observatory.webgl.body')}</p>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.location.reload()}>
            <RotateCw className="h-4 w-4" aria-hidden />
            {t('common.reload')}
          </button>
        </div>
      )}
      {hovered && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-[8] w-[210px] -translate-x-1/2 -translate-y-full rounded-[11px] border border-line bg-surface/90 px-3.5 py-3 text-ink shadow-gilt backdrop-blur-md md:w-[238px]"
          style={{ left: hovered.x, top: hovered.y }}
        >
          {renderHover(hovered.id)}
        </div>
      )}
    </div>
  );
});

export default ObservatoryScene;
