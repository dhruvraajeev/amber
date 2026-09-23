import { ChevronLeft, ChevronRight, Pause, Play } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import { lastPoint } from '../store/runSlice'
import { usePlaybackClock } from './Playback'

// Step, play/pause, step, and a scrubber over the result's timeline (§11.3), floating at the foot of the
// canvas like a player's transport, since the canvas is what follows the playhead. Space plays too (RunBar).
export default function PlaybackBar() {
  const { result, playhead, playing, setPlayhead, togglePlay } = useStore(
    useShallow((s) => ({ result: s.result, playhead: s.playhead, playing: s.playing, setPlayhead: s.setPlayhead, togglePlay: s.togglePlay })),
  )
  usePlaybackClock()
  if (!result) return null
  const t = result.timeline[playhead]?.t ?? 0
  const last = lastPoint(result)
  return (
    <div
      className="absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full border border-border bg-panel/85 py-1.5 pr-4 pl-1.5 shadow-[0_18px_40px_-20px_rgb(0_0_0/0.9)] backdrop-blur-sm"
      role="group" aria-label="Playback"
    >
      <button className="btn-icon size-8" onClick={() => setPlayhead(playhead - 1)} disabled={playhead === 0} aria-label="Step back">
        <ChevronLeft size={15} aria-hidden />
      </button>
      <button
        className="btn-icon size-9 border-accent/40 text-accent shadow-[0_0_18px_-6px_rgb(255_106_43/0.8)]"
        onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'} aria-keyshortcuts="Space" title="Play/pause (Space)"
      >
        {playing ? <Pause size={15} fill="currentColor" aria-hidden /> : <Play size={15} fill="currentColor" className="translate-x-px" aria-hidden />}
      </button>
      <button className="btn-icon size-8" onClick={() => setPlayhead(playhead + 1)} disabled={playhead === last} aria-label="Step forward">
        <ChevronRight size={15} aria-hidden />
      </button>
      <input
        type="range" min={0} max={last} value={playhead}
        onChange={(e) => setPlayhead(e.target.valueAsNumber)}
        aria-label="Timeline position" aria-valuetext={`${t} seconds`}
        style={{ '--fill': `${last ? (playhead / last) * 100 : 0}%` } as CSSProperties}
        className="ml-1 w-40"
      />
      <span className="num w-[4.5rem] text-xs whitespace-nowrap text-muted">
        <span className="text-text">{t}</span> / {result.config.durationS} s
      </span>
    </div>
  )
}
