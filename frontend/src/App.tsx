import { useState } from 'react';

interface RunResponse {
  error: string | null;
  needs_clarification: boolean;
  clarifying_question: string | null;
  validation_warnings: string[];
  report_text: string | null;
  map_html: string | null;
}

function App() {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<RunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setResponse(null);

    try {
      const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');
      const res = await fetch(`${apiBase}/api/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ prompt }),
      });

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}`);
      }

      const data: RunResponse = await res.json();
      setResponse(data);
      if (data.error) {
        setError(data.error);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Equilibria</h1>
        <p>Run the siting and equity pipeline from your browser.</p>
      </header>

      <main>
        <form onSubmit={handleSubmit} className="run-form">
          <label htmlFor="prompt">Enter a planning prompt</label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={6}
            placeholder="e.g. Identify candidate health facility sites for Kano State, Nigeria"
          />
          <button type="submit" disabled={loading || prompt.trim().length === 0}>
            {loading ? 'Running…' : 'Run Equilibria'}
          </button>
        </form>

        {error ? <div className="error-box">{error}</div> : null}

        {response ? (
          <section className="results">
            <h2>Pipeline results</h2>
            {response.needs_clarification ? (
              <div className="warning-box">
                <strong>Clarification needed:</strong> {response.clarifying_question}
              </div>
            ) : null}

            {response.validation_warnings.length > 0 ? (
              <div className="warning-box">
                <strong>Validation warnings:</strong>
                <ul>
                  {response.validation_warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {response.report_text ? (
              <section className="report">
                <h3>Report</h3>
                <pre>{response.report_text}</pre>
              </section>
            ) : null}

            {response.map_html ? (
              <section className="map-preview">
                <h3>Map</h3>
                <div
                  className="map-frame"
                  dangerouslySetInnerHTML={{ __html: response.map_html }}
                />
              </section>
            ) : null}
          </section>
        ) : null}
      </main>
    </div>
  );
}

export default App;
