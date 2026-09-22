import { useState } from "react";
import { api, useApi } from "../lib/api";
import BrandIcon from "../components/BrandIcon";
import Loading from "./Loading";

/* Settings, Home page: the links everyone lands on.
 *
 * The services that are set up are offered without anyone adding them. This is
 * where they get a different name, a different audience, an order, or where
 * links of your own go. */

type Link = {
  key: string;
  label: string;
  url: string;
  icon: string;
  roles: string;
  position: number;
  hidden: boolean;
  custom: boolean;
};

const WHO: { id: string; label: string }[] = [
  { id: "all", label: "Everyone" },
  { id: "admin", label: "Admins" },
  { id: "viewer", label: "Viewers" },
];

export default function HomeLinks() {
  const links = useApi<Link[]>("/home/links");
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [roles, setRoles] = useState("all");

  async function act(run: () => Promise<unknown>) {
    setError(null);
    try {
      await run();
      links.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (links.error) return <p className="note bad-note">{links.error}</p>;
  if (!links.data) return <Loading label="Reading the home page" />;

  return (
    <>
      <section className="card-section">
        <h3>Links</h3>
        <p className="muted small">
          Anything you have set up is offered here already. Hide what nobody needs, and choose who sees the rest.
        </p>
        {error && <p className="note bad-note">{error}</p>}
        <div className="mini-list">
          {links.data.map((link, index) => (
            <div key={link.key} className={link.hidden ? "mini home-link-row off" : "mini home-link-row"}>
              <div className="min0">
                <div className="row">
                  {link.icon && <BrandIcon name={link.icon} size={16} />}
                  <input
                    value={link.label}
                    onChange={(e) =>
                      act(() => api.put(`/home/links/${link.key}`, { label: e.target.value || link.label }))
                    }
                  />
                </div>
                <p className="muted small clip">{link.url}</p>
              </div>
              <div className="row">
                <select value={link.roles} onChange={(e) => act(() => api.put(`/home/links/${link.key}`, { roles: e.target.value }))}>
                  {WHO.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.label}
                    </option>
                  ))}
                </select>
                <button
                  className="tab"
                  disabled={index === 0}
                  title="Move up"
                  onClick={() => act(() => api.put(`/home/links/${link.key}`, { position: Math.max(0, index - 1) }))}
                >
                  Up
                </button>
                {link.hidden ? (
                  <button className="tab" onClick={() => act(() => api.put(`/home/links/${link.key}`, { hidden: false }))}>
                    Show
                  </button>
                ) : (
                  <button className="tab" onClick={() => act(() => api.del(`/home/links/${link.key}`))}>
                    {link.custom ? "Delete" : "Hide"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="card-section">
        <h3>Add a link</h3>
        <div className="row wrap">
          <input placeholder="Name" value={label} onChange={(e) => setLabel(e.target.value)} />
          <input placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} />
          <select value={roles} onChange={(e) => setRoles(e.target.value)}>
            {WHO.map((w) => (
              <option key={w.id} value={w.id}>
                {w.label}
              </option>
            ))}
          </select>
          <button
            className="btn"
            disabled={!label.trim() || !url.trim()}
            onClick={async () => {
              await act(() => api.post("/home/links", { label, url, roles }));
              setLabel("");
              setUrl("");
            }}
          >
            Add
          </button>
        </div>
      </section>
    </>
  );
}
