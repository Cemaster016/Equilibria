import { useState, useRef, useEffect } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const AGENTS = [
  { id: 1, name: "IntakeAgent",        desc: "Parsing mission brief" },
  { id: 2, name: "DataFetcherAgent",   desc: "Fetching open geodata" },
  { id: 3, name: "EquityScoringAgent", desc: "Scoring population grid" },
  { id: 4, name: "SiteOptimizerAgent", desc: "Selecting optimal sites" },
  { id: 5, name: "ValidatorAgent",     desc: "Governance checks" },
  { id: 6, name: "CartographerAgent",  desc: "Rendering coverage map" },
  { id: 7, name: "ReportAgent",        desc: "Writing policy brief" },
];

const EXAMPLE =
  "Suggest 3 new clinic sites in Kano State, Nigeria — prioritise underserved children with poor road access.";

type StepStatus = "idle" | "active" | "done";

interface Result {
  map_html: string;
  report_text: string;
  validation_warnings: string[];
  chosen_sites_geojson: string;
  needs_clarification: boolean;
  clarifying_question: string | null;
  error: string | null;
}

export default function App() {
  const [prompt, setPrompt] = useState(EXAMPLE);
  const [running, setRunning] = useState(false);
  const [stepStatus, setStepStatus] = useState<StepStatus[]>(
    Array(7).fill("idle")
  );
  const [result, setResult] = useState<Result | null>(null);
  const [tab, setTab] = useState<"map" | "report" | "validation">("map");
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      timerRef.current = setInterval(
        () => setElapsed((e) => e + 1),
        1000
      );
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [running]);

  const simulateProgress = async () => {
    const timings = [800, 3000, 5000, 4000, 1200, 2000, 3000];
    for (let i = 0; i < 7; i++) {
      setStepStatus((s) =>
        s.map((v, idx) =>
          idx === i ? "active" : idx < i ? "done" : v
        )
      );
      await new Promise((r) => setTimeout(r, timings[i]));
    }
    setStepStatus(Array(7).fill("done"));
  };

  const run = async () => {
    if (!prompt.trim() || running) return;
    setRunning(true);
    setResult(null);
    setElapsed(0);
    setStepStatus(Array(7).fill("idle"));

    const progressPromise = simulateProgress();

    try {
      const res = await fetch(`${API_URL}/api/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data: Result = await res.json();
      await progressPromise;
      setResult(data);
      setTab("map");
    } catch (err) {
      await progressPromise;
      setResult({
        map_html: "",
        report_text: "",
        validation_warnings: [],
        chosen_sites_geojson: "",
        needs_clarification: false,
        clarifying_question: null,
        error: String(err),
      });
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html, body, #root { height: 100%; }
        body {
          background: #04080f;
          color: #e2e8f0;
          font-family: 'Inter', sans-serif;
          overflow: hidden;
        }

        /* ── grid + radar background ── */
        .bg-grid {
          position: fixed; inset: 0; z-index: 0; pointer-events: none;
          background-image:
            linear-gradient(rgba(6,182,212,.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(6,182,212,.05) 1px, transparent 1px);
          background-size: 40px 40px;
        }
        .bg-radar {
          position: fixed; top: -180px; right: -180px;
          width: 520px; height: 520px; border-radius: 50%;
          border: 1px solid rgba(6,182,212,.08);
          pointer-events: none; z-index: 0;
        }
        .bg-radar::before {
          content: ''; position: absolute; inset: 60px;
          border-radius: 50%; border: 1px solid rgba(6,182,212,.06);
        }
        .bg-radar::after {
          content: ''; position: absolute; inset: 120px;
          border-radius: 50%; border: 1px solid rgba(6,182,212,.04);
        }
        .radar-sweep {
          position: absolute; top: 50%; left: 50%;
          width: 50%; height: 2px;
          transform-origin: left center;
          background: linear-gradient(90deg, rgba(6,182,212,0), rgba(6,182,212,.5));
          animation: sweep 6s linear infinite;
        }
        @keyframes sweep {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }

        /* ── layout ── */
        .shell {
          position: relative; z-index: 1;
          height: 100vh;
          display: flex; flex-direction: column;
        }

        /* ── header ── */
        .hdr {
          display: flex; align-items: center; gap: 14px;
          padding: 14px 28px;
          border-bottom: 1px solid rgba(6,182,212,.12);
          background: rgba(4,8,15,.85);
          backdrop-filter: blur(8px);
          flex-shrink: 0;
        }
        .hdr-dot {
          width: 10px; height: 10px; border-radius: 50%;
          background: #06b6d4;
          box-shadow: 0 0 12px #06b6d4;
          animation: glow 2s ease-in-out infinite;
        }
        @keyframes glow {
          0%,100% { box-shadow: 0 0 8px #06b6d4; }
          50%      { box-shadow: 0 0 22px #06b6d4, 0 0 44px rgba(6,182,212,.3); }
        }
        .hdr-name {
          font-family: 'Space Grotesk', sans-serif;
          font-size: 20px; font-weight: 700; letter-spacing: .1em;
        }
        .hdr-badge {
          font-size: 10px; letter-spacing: .1em; text-transform: uppercase;
          color: #06b6d4;
          background: rgba(6,182,212,.1);
          border: 1px solid rgba(6,182,212,.25);
          border-radius: 4px; padding: 3px 9px;
        }
        .hdr-right {
          margin-left: auto;
          font-family: 'JetBrains Mono', monospace;
          font-size: 11px; color: #334155;
        }

        /* ── body split ── */
        .body {
          flex: 1; display: grid;
          grid-template-columns: 300px 1fr;
          overflow: hidden;
        }

        /* ── left panel ── */
        .panel {
          border-right: 1px solid rgba(6,182,212,.1);
          background: rgba(4,8,15,.65);
          backdrop-filter: blur(4px);
          padding: 20px;
          display: flex; flex-direction: column; gap: 18px;
          overflow-y: auto;
        }
        .lbl {
          font-size: 10px; letter-spacing: .14em;
          text-transform: uppercase; color: #334155;
          margin-bottom: 7px;
        }
        .prompt-wrap {
          background: rgba(6,182,212,.04);
          border: 1px solid rgba(6,182,212,.2);
          border-radius: 8px; overflow: hidden;
        }
        .prompt-input {
          width: 100%; background: transparent;
          border: none; outline: none;
          color: #e2e8f0;
          font-family: 'Inter', sans-serif;
          font-size: 13px; line-height: 1.7;
          padding: 13px; resize: none; min-height: 96px;
        }
        .prompt-input::placeholder { color: #334155; }

        .run-btn {
          width: 100%; padding: 12px;
          background: rgba(6,182,212,.12);
          border: 1px solid #06b6d4; border-radius: 8px;
          color: #06b6d4;
          font-family: 'Space Grotesk', sans-serif;
          font-size: 13px; font-weight: 600; letter-spacing: .08em;
          cursor: pointer; transition: .2s;
          display: flex; align-items: center; justify-content: center; gap: 10px;
        }
        .run-btn:hover:not(:disabled) {
          background: rgba(6,182,212,.22);
          box-shadow: 0 0 20px rgba(6,182,212,.15);
        }
        .run-btn:disabled { opacity: .45; cursor: not-allowed; }
        .run-btn.is-running {
          background: #06b6d4; color: #04080f;
          box-shadow: 0 0 28px rgba(6,182,212,.4);
        }

        .timer {
          font-family: 'JetBrains Mono', monospace;
          font-size: 11px; color: #475569;
          text-align: right; margin-top: -10px;
        }

        /* ── pipeline steps ── */
        .pipeline { display: flex; flex-direction: column; gap: 3px; }
        .step {
          display: flex; align-items: center; gap: 10px;
          padding: 9px 10px; border-radius: 6px;
          border: 1px solid transparent; transition: .25s;
        }
        .step-idle  { border-color: rgba(255,255,255,.04); }
        .step-active {
          border-color: rgba(6,182,212,.45);
          background: rgba(6,182,212,.08);
          animation: stepglow .9s ease-in-out infinite alternate;
        }
        @keyframes stepglow {
          from { border-color: rgba(6,182,212,.2); background: rgba(6,182,212,.04); }
          to   { border-color: rgba(6,182,212,.6); background: rgba(6,182,212,.12); }
        }
        .step-done {
          border-color: rgba(16,185,129,.2);
          background: rgba(16,185,129,.05);
        }
        .step-num {
          width: 20px; height: 20px; border-radius: 50%;
          font-size: 9px; font-weight: 700;
          display: flex; align-items: center; justify-content: center;
          flex-shrink: 0;
        }
        .num-idle   { background: rgba(255,255,255,.06); color: #334155; }
        .num-active { background: #06b6d4; color: #04080f; }
        .num-done   { background: #10b981; color: #04080f; }
        .step-info { flex: 1; }
        .step-name-idle   { font-size: 11px; color: #475569; font-weight: 500; }
        .step-name-active { font-size: 11px; color: #e2e8f0; font-weight: 500; }
        .step-name-done   { font-size: 11px; color: #10b981; font-weight: 500; }
        .step-desc        { font-size: 10px; color: #334155; margin-top: 1px; }
        .step-desc-active { font-size: 10px; color: #06b6d4; margin-top: 1px; }

        /* ── right results ── */
        .results { display: flex; flex-direction: column; overflow: hidden; }
        .tabs {
          display: flex; flex-shrink: 0;
          border-bottom: 1px solid rgba(6,182,212,.1);
          background: rgba(4,8,15,.75);
          backdrop-filter: blur(4px);
        }
        .tab-btn {
          padding: 15px 24px; font-size: 12px; font-weight: 500;
          letter-spacing: .05em; color: #475569;
          cursor: pointer; border: none; background: transparent;
          border-bottom: 2px solid transparent; transition: .15s;
        }
        .tab-btn:hover { color: #94a3b8; }
        .tab-btn.active { color: #06b6d4; border-bottom-color: #06b6d4; }

        .result-body {
          flex: 1; padding: 24px; overflow-y: auto;
        }

        /* ── empty state ── */
        .empty {
          height: 100%;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          gap: 16px; color: #1e293b;
        }
        .empty-icon { font-size: 52px; opacity: .35; }
        .empty-text { font-size: 13px; letter-spacing: .06em; text-transform: uppercase; }

        /* ── result cards ── */
        .map-frame {
          width: 100%;
          height: calc(100vh - 170px);
          border: none; border-radius: 8px;
          background: #0a1628;
        }
        .report-body {
          max-width: 700px; font-size: 14px;
          line-height: 1.85; color: #cbd5e1;
          white-space: pre-wrap;
        }
        .report-body h2 {
          font-family: 'Space Grotesk', sans-serif;
          font-size: 13px; font-weight: 600;
          color: #06b6d4; letter-spacing: .08em;
          text-transform: uppercase;
          margin: 24px 0 8px;
        }
        .warnings { display: flex; flex-direction: column; gap: 10px; }
        .warn-ok {
          background: rgba(16,185,129,.06);
          border: 1px solid rgba(16,185,129,.2);
          border-radius: 8px; padding: 14px 16px;
          font-size: 13px; color: #10b981;
          display: flex; align-items: center; gap: 10px;
        }
        .warn-flag {
          background: rgba(234,179,8,.06);
          border: 1px solid rgba(234,179,8,.2);
          border-radius: 8px; padding: 14px 16px;
          font-size: 13px; color: #fbbf24; line-height: 1.6;
          display: flex; gap: 10px;
        }
        .err-card {
          background: rgba(239,68,68,.06);
          border: 1px solid rgba(239,68,68,.2);
          border-radius: 8px; padding: 14px 16px;
          font-size: 13px; color: #f87171; line-height: 1.6;
        }
        .clarify-card {
          background: rgba(6,182,212,.06);
          border: 1px solid rgba(6,182,212,.2);
          border-radius: 8px; padding: 14px 16px;
          font-size: 13px; color: #67e8f9; line-height: 1.6;
          display: flex; flex-direction: column; gap: 8px;
        }
      `}</style>

      {/* background */}
      <div className="bg-grid" />
      <div className="bg-radar">
        <div className="radar-sweep" />
      </div>

      <div className="shell">
        {/* header */}
        <header className="hdr">
          <div className="hdr-dot" />
          <span className="hdr-name">EQUILIBRIA</span>
          <span className="hdr-badge">Agents for Good</span>
          <span className="hdr-right">
            {running
              ? "SCANNING · LOCATION AI · EQUITY SITING"
              : "LOCATION AI · EQUITY SITING"}
          </span>
        </header>

        <div className="body">
          {/* left panel */}
          <aside className="panel">
            <div>
              <div className="lbl">Mission Brief</div>
              <div className="prompt-wrap">
                <textarea
                  className="prompt-input"
                  rows={5}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Describe what you need sited and where…"
                />
              </div>
            </div>

            <button
              className={`run-btn${running ? " is-running" : ""}`}
              onClick={run}
              disabled={running || !prompt.trim()}
            >
              {running ? "⟳  AGENTS RUNNING" : "▶  DEPLOY AGENTS"}
            </button>

            {(running || elapsed > 0) && (
              <div className="timer">
                {running
                  ? `${elapsed}s elapsed`
                  : `Completed in ${elapsed}s`}
              </div>
            )}

            <div>
              <div className="lbl">Pipeline Status</div>
              <div className="pipeline">
                {AGENTS.map((agent, i) => {
                  const st = stepStatus[i];
                  return (
                    <div
                      key={agent.id}
                      className={`step step-${st}`}
                    >
                      <div
                        className={`step-num num-${st}`}
                      >
                        {st === "done" ? "✓" : agent.id}
                      </div>
                      <div className="step-info">
                        <div className={`step-name-${st}`}>
                          {agent.name}
                        </div>
                        <div
                          className={
                            st === "active"
                              ? "step-desc-active"
                              : "step-desc"
                          }
                        >
                          {agent.desc}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </aside>

          {/* right results */}
          <div className="results">
            <div className="tabs">
              {(["map", "report", "validation"] as const).map((t) => (
                <button
                  key={t}
                  className={`tab-btn${tab === t ? " active" : ""}`}
                  onClick={() => setTab(t)}
                >
                  {t === "map"
                    ? "🗺  Map"
                    : t === "report"
                    ? "📄  Report"
                    : "🛡  Validation"}
                </button>
              ))}
            </div>

            <div className="result-body">
              {/* empty state */}
              {!result && !running && (
                <div className="empty">
                  <div className="empty-icon">🧭</div>
                  <div className="empty-text">
                    Enter a mission brief and deploy agents
                  </div>
                </div>
              )}

              {/* error */}
              {result?.error && (
                <div className="err-card">⚠ {result.error}</div>
              )}

              {/* clarification */}
              {result?.needs_clarification && (
                <div className="clarify-card">
                  <strong>One question before we proceed:</strong>
                  {result.clarifying_question}
                </div>
              )}

              {/* map */}
              {result &&
                !result.error &&
                !result.needs_clarification &&
                tab === "map" &&
                (result.map_html ? (
                  <iframe
                    srcDoc={result.map_html}
                    className="map-frame"
                    title="Coverage map"
                  />
                ) : (
                  <div className="empty">
                    <div className="empty-text">Map not available</div>
                  </div>
                ))}

              {/* report */}
              {result &&
                !result.error &&
                !result.needs_clarification &&
                tab === "report" && (
                  <div className="report-body">
                    {result.report_text || "Report not available."}
                  </div>
                )}

              {/* validation */}
              {result &&
                !result.error &&
                !result.needs_clarification &&
                tab === "validation" && (
                  <div className="warnings">
                    {result.validation_warnings.length === 0 ? (
                      <div className="warn-ok">
                        ✓ No data-quality or bias concerns flagged.
                      </div>
                    ) : (
                      result.validation_warnings.map((w, i) => (
                        <div key={i} className="warn-flag">
                          <span>⚠</span>
                          <span>{w}</span>
                        </div>
                      ))
                    )}
                  </div>
                )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
