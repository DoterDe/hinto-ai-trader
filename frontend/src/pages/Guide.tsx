import { useState } from "react";
import { modules, terms } from "../help/Help";
import { Card } from "../components/Common";
import type { Page } from "../types";

export function Guide({ navigate }: { navigate: (page: Page) => void }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(modules[0]);
  const destination = (page: string): Page =>
    page === "Guide" ? "Guide / How It Works" : (page as Page);
  return (
    <>
      <div className="intro-panel">
        <span className="eyebrow">UNDERSTAND THE WORKSTATION</span>
        <h2>Observe. Explain. Simulate.</h2>
        <p>
          Follow a public candle through the system. Every block below can
          explain its output. None can move money.
        </p>
      </div>
      <div className="two-columns">
        <Card title="How information flows" help="paper">
          <ol className="architecture">
            {modules.map((m, i) => (
              <li key={m.key}>
                <button
                  onClick={() => setActive(m)}
                  aria-pressed={active.key === m.key}
                >
                  <span>{String(i + 1).padStart(2, "0")}</span>
                  {m.name}
                  <span aria-hidden="true">↗</span>
                </button>
              </li>
            ))}
          </ol>
        </Card>
        <Card title={active.name} help="paper">
          <dl className="explain-list">
            <dt>Purpose</dt>
            <dd>{active.purpose}</dd>
            <dt>Input</dt>
            <dd>{active.inputs}</dd>
            <dt>Output</dt>
            <dd>{active.outputs}</dd>
            <dt>Limitations</dt>
            <dd>{active.limitations}</dd>
            <dt>Can move money?</dt>
            <dd>No.</dd>
            <dt>Source module</dt>
            <dd>
              <code>{active.source_path}</code>
            </dd>
          </dl>
          <button
            className="text-button"
            onClick={() => navigate(destination(active.page))}
          >
            View {active.page} →
          </button>
        </Card>
      </div>
      <Card title="A simple example" help="horizon">
        <p>
          A finalized candle produces an eligible analytical record. If virtual
          capacity is available, the policy reserves it. When the next exact
          candle has finalized, its open becomes the hypothetical entry. After
          five complete holding bars, the fixed horizon closes the position with
          assumed costs.
        </p>
        <p>
          A missing required bar stays missing. The application never invents a
          price to finish a position.
        </p>
      </Card>
      <Card title="Glossary" help="features">
        <label className="search-label">
          Find a term
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Try confidence, drawdown or EMA"
          />
        </label>
        <div className="glossary">
          {terms
            .filter((t) =>
              `${t.label} ${t.explanation}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((t) => (
              <article key={t.key} id={`term-${t.key}`}>
                <h3>{t.label}</h3>
                <p>{t.explanation}</p>
              </article>
            ))}
        </div>
      </Card>
    </>
  );
}
