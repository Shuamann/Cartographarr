import { useEffect, useRef, useState } from "react";

/* Where a stream has got to, between the moments anybody asks.
 *
 * Live activity is read on a timer, and used to be read every five seconds, so
 * a position sat still for five seconds and then jumped five seconds. Plex now
 * pushes an event the moment a stream starts, stops or pauses, which makes the
 * jumps irregular as well as large: the number is right twice a minute and
 * wrong in a way the eye follows the rest of the time.
 *
 * Nothing here invents a fact. A stream that is playing is playing, so between
 * two readings it has advanced by the time that passed, and that is the whole
 * of the assumption. Each reading from the server replaces the guess outright
 * rather than being averaged into it, so a seek, a pause or a stall lands on
 * the next poll and the number never drifts away from the truth for longer
 * than one interval.
 *
 * It stops dead when the state is anything but playing, which is the half that
 * makes it honest: a paused stream whose timer kept climbing would be a lie
 * told smoothly.
 */
export function useRunningOffset(offset: number, playing: boolean, duration: number): number {
  const [shown, setShown] = useState(offset);
  // What the server last said, and when it said it.
  const told = useRef({ offset, at: Date.now() });

  useEffect(() => {
    told.current = { offset, at: Date.now() };
    setShown(offset);
  }, [offset]);

  useEffect(() => {
    if (!playing) return;
    const tick = window.setInterval(() => {
      const since = Date.now() - told.current.at;
      const next = told.current.offset + since;
      // Never past the end. A film that has finished is not still playing, and
      // a bar that fills past its track looks broken.
      setShown(duration > 0 ? Math.min(next, duration) : next);
    }, 1000);
    return () => window.clearInterval(tick);
  }, [playing, duration]);

  return shown;
}

/* The same position as a percentage, worked out here rather than taken from
   the server's, so the bar and the clock cannot disagree with each other. */
export function runningPercent(offset: number, duration: number): number {
  if (!(duration > 0)) return 0;
  return Math.min(Math.max((offset / duration) * 100, 0), 100);
}
