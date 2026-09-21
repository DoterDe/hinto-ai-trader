import { useState } from "react";
import { pages, type Page, type Snapshot } from "../types";
import type { Telemetry } from "../hooks/useTelemetry";
import { Badge, Empty } from "../components/Common";
import { Help } from "../help/Help";
import { Overview } from "../pages/Overview";
import { Guide } from "../pages/Guide";
import { System } from "../pages/System";
import { MarketPage } from "../pages/Market";
import { Signals } from "../pages/Signals";
import { Portfolio } from "../pages/Portfolio";
import { Backtest } from "../pages/Backtest";
import { time, words } from "../utils/format";

const subtitles: Record<Page, string> = {
  Overview: "Public market evidence. Explainable decisions. Virtual capital.",
  Market:
    "Current public observations and the exact measurements behind paper decisions.",
  "Signals & Decisions":
    "Trace every analytical result from evidence to virtual portfolio policy.",
  "Paper Portfolio":
    "A shared virtual capital pool. Every reservation, mark and cost explained.",
  "Backtest & Validation":
    "Understand what historical evidence can—and cannot—tell you.",
  "System / Settings":
    "Read-only configuration, software health and simulation boundaries.",
  "Guide / How It Works":
    "A plain-language map of every module in the workstation.",
};

function initialView() {
  try {
    return localStorage.getItem("hinto.view") === "advanced";
  } catch {
    return false;
  }
}

export function Dashboard({ telemetry }: { telemetry: Telemetry }) {
  const [page, setPage] = useState<Page>("Overview");
  const [advanced, setAdvanced] = useState(initialView);
  const data = telemetry.data;
  function toggle(value: boolean) {
    setAdvanced(value);
    try {
      localStorage.setItem("hinto.view", value ? "advanced" : "simple");
    } catch {
      /* Storage can be disabled. */
    }
  }
  function content(data?: Snapshot) {
    if (page === "Guide / How It Works") return <Guide navigate={setPage} />;
    if (page === "System / Settings")
      return <System data={data} advanced={advanced} />;
    if (page === "Backtest & Validation") return <Backtest advanced={advanced} />;
    if (!data)
      return (
        <div className="card">
          <Empty>
            {telemetry.connection === "loading"
              ? "Loading public-data telemetry…"
              : "Backend unavailable. Start the backend to see observed data. Guide and System remain available."}
          </Empty>
        </div>
      );
    if (page === "Overview") return <Overview data={data} advanced={advanced} />;
    if (page === "Market")
      return <MarketPage data={data} advanced={advanced} />;
    if (page === "Signals & Decisions")
      return <Signals data={data} advanced={advanced} />;
    return <Portfolio data={data} advanced={advanced} />;
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("Overview");
          }}
        >
          <span className="brand-mark">H</span>
          <span>
            HINTO<small>RESEARCH WORKSTATION</small>
          </span>
        </a>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="Main navigation">
          {pages.map((name, index) => (
            <button
              key={name}
              aria-current={page === name ? "page" : undefined}
              onClick={() => setPage(name)}
            >
              <span className="nav-number">0{index + 1}</span>
              <span>{name}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="eyebrow">PUBLIC DATA · VIRTUAL CAPITAL</span>
          <p>
            Every result is observable.
            <br />
            Every action stays simulated.
          </p>
          <span className="version">PHASE 10 / research validation</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="mode-badge">
            PAPER / VIRTUAL ONLY <Help name="paper" />
          </span>
          <div className="topbar-right">
            <span className="connection" role="status">
              Backend{" "}
              {telemetry.connection === "connected"
                ? "connected"
                : telemetry.connection === "loading"
                  ? "connecting"
                  : "unavailable"}
            </span>
            <div
              className="view-toggle"
              role="group"
              aria-label="Display preference"
            >
              <button aria-pressed={!advanced} onClick={() => toggle(false)}>
                Simple
              </button>
              <button aria-pressed={advanced} onClick={() => toggle(true)}>
                Advanced
              </button>
            </div>
          </div>
        </header>
        <main id="main-content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                HINTO / {String(pages.indexOf(page) + 1).padStart(2, "0")}
              </span>
              <h1>{page}</h1>
              <p>{subtitles[page]}</p>
            </div>
            <Badge
              value={
                data?.status.status ??
                (telemetry.connection === "loading" ? "LOADING" : "UNKNOWN")
              }
            />
          </div>
          {data && (
            <div className="health-strip">
              <span>
                Public feed{" "}
                <Badge
                  value={data.status.market.stale ? "STALE / PARTIAL" : "FRESH"}
                />
              </span>
              <span>
                Valuation{" "}
                <Badge
                  value={
                    data.portfolio.valuation_complete
                      ? "KNOWN AS OF BAR"
                      : "UNKNOWN"
                  }
                />
              </span>
              <span>As of {time(data.as_of)}</span>
            </div>
          )}
          {data?.status.reasons.length ? (
            <div className="notice" role="status">
              <strong>{data.status.status.replaceAll("_", " ")}</strong> ·{" "}
              {data.status.reasons.map(words).join(" · ")} <Help name="stale" />
            </div>
          ) : null}
          {data && !data.portfolio.valuation_complete && (
            <div className="notice" role="alert">
              Unknown valuation — required price evidence or a valid portfolio
              state is unavailable. Unresolved exposure remains visible; no exit
              is invented.
            </div>
          )}
          {telemetry.connection === "unavailable" && (
            <div className="notice" role="alert">
              Backend unavailable. Retrying automatically. No previous valuation
              is presented as current.
            </div>
          )}
          {content(data)}
          <footer>
            Public-data research and virtual simulation only. Historical
            simulation does not predict future performance.
          </footer>
        </main>
      </div>
    </div>
  );
}
