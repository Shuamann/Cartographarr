import { useState } from "react";
import { useApi } from "../lib/api";
import TitleRow, { TitleRows } from "./TitleRow";

type Recap = {
  days: number;
  plays: number;
  hours: number;
  hours_before: number | null;
  days_watched: number;
  devices: number;
  shows_started: number;
  busiest_weekday: string | null;
  busiest_hour: number | null;
  biggest_day: { date: string; hours: number } | null;
  top: { rating_key: number; title: string | null; media_type: string | null; year: number | null; hours: number; plays: number }[];
  genres: { genre: string; hours: number }[];
};

const SPANS: [number, string][] = [
  [30, "Month"],
  [365, "Year"],
];

function hourName(hour: number): string {
  const h = hour % 12 || 12;
  return `${h} ${hour < 12 ? "am" : "pm"}`;
}

/* Against the window before, so a number of hours has something to be more
 * or less than. Nothing when there was nothing then. */
function change(now: number, before: number | null): string | null {
  if (!before) return null;
  const pct = Math.round(((now - before) / before) * 100);
  if (pct === 0) return "the same as the one before";
  return `${Math.abs(pct)}% ${pct > 0 ? "more" : "less"} than the one before`;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="spec-pair">
      <dt>{label}</dt>
      <dd>
        <span>{children}</span>
      </dd>
    </div>
  );
}

/* A person's month or year, in a screenful: how long, what, when, on what.
 * Every number was already in their history; this adds it up. */
export default function RecapView({ userId }: { userId: number }) {
  const [days, setDays] = useState(30);
  const r = useApi<Recap>(`/users/${userId}/recap?days=${days}`);
  const d = r.data;

  return (
    <section className="profile-section recap">
      <div className="segmented">
        {SPANS.map(([span, label]) => (
          <button key={span} className={days === span ? "seg on" : "seg"} onClick={() => setDays(span)}>
            {label}
          </button>
        ))}
      </div>
      {r.error && (
        <p className="note bad-note" role="alert">
          {r.error}
        </p>
      )}
      {d && d.plays === 0 && <p className="muted">Nothing watched in the last {days === 30 ? "month" : "year"}.</p>}
      {d && d.plays > 0 && (
        <>
          <p className="recap-lead">
            <strong>{d.hours.toLocaleString()} hours</strong> over {d.plays.toLocaleString()} plays
            {change(d.hours, d.hours_before) ? `, ${change(d.hours, d.hours_before)}` : ""}.
          </p>
          <dl className="spec profile-facts">
            <Fact label="Days">{d.days_watched} with something on</Fact>
            <Fact label="Started">
              {d.shows_started} new {d.shows_started === 1 ? "show" : "shows"}
            </Fact>
            {d.busiest_weekday && <Fact label="Mostly">{`${d.busiest_weekday}s, around ${hourName(d.busiest_hour ?? 0)}`}</Fact>}
            {d.biggest_day && (
              <Fact label="Biggest">
                {new Date(`${d.biggest_day.date}T12:00:00`).toLocaleDateString()}, {d.biggest_day.hours} hours
              </Fact>
            )}
            <Fact label="Devices">{d.devices}</Fact>
          </dl>

          <h3>Most watched</h3>
          <TitleRows>
            {d.top.map((t) => (
              <TitleRow
                key={t.rating_key}
                ratingKey={t.rating_key}
                item={{ title: t.title, full_title: t.title, media_type: t.media_type, year: t.year }}
                facts={[
                  { label: "Hours", value: t.hours },
                  { label: "Plays", value: t.plays },
                ]}
              />
            ))}
          </TitleRows>

          {d.genres.length > 0 && (
            <>
              <h3>Genres</h3>
              <div className="report-bars">
                {d.genres.map((g) => (
                  <div className="report-bar-row" key={g.genre}>
                    <div className="report-bar-label">
                      <span>{g.genre}</span>
                    </div>
                    <div className="report-bar-track">
                      <div className="report-bar-fill" style={{ width: `${(g.hours / d.genres[0].hours) * 100}%` }} />
                    </div>
                    <div className="report-bar-value">{g.hours} h</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
