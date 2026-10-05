import { useState } from "react";

/**
 * The retraction panel is the point of this screen.
 *
 * Most review tools show you what they found. This one shows what it found
 * *and* what it threw away, side by side, because the second number is the
 * one that decides whether the bot stays switched on. Hiding retractions
 * would make the tool look more productive and less trustworthy.
 */
export default function Index() {
  const [path, setPath] = useState("C:\\src\\rag-forge");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("confirmed");

  async function scan() {
    setBusy(true);
    setError("");
    setData(null);
    try {
      const response = await fetch(`/api/scan?path=${encodeURIComponent(path)}`);
      const payload = await response.json();
      if (payload.error) setError(payload.error);
      else setData(payload);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  const rows = data
    ? data.files.flatMap((file) =>
        file.verdicts
          .filter((v) => (tab === "confirmed" ? v.confirmed : !v.confirmed))
          .map((v) => ({ ...v, path: file.path }))
      )
    : [];

  return (
    <main>
      <header>
        <h1>review-bot</h1>
        <p className="sub">
          Every finding is proposed, then attacked. Only what survives is reported, and
          what did not is shown next to it — precision is the whole product.
        </p>
      </header>

      <div className="row">
        <input value={path} onChange={(e) => setPath(e.target.value)}
               onKeyUp={(e) => e.key === "Enter" && scan()} />
        <button onClick={scan} disabled={busy}>{busy ? "Reviewing…" : "Review"}</button>
      </div>

      {error ? <p className="err">{error}</p> : null}

      {data ? (
        <>
          <div className="stats">
            <div className="stat ok">
              <div className="v">{data.confirmed}</div>
              <div className="k">reported</div>
            </div>
            <div className="stat warn">
              <div className="v">{data.retracted}</div>
              <div className="k">retracted before posting</div>
            </div>
            <div className="stat">
              <div className="v">{Math.round(data.retraction_rate * 100)}%</div>
              <div className="k">retraction rate</div>
            </div>
            <div className="stat">
              <div className="v">{data.proposed}</div>
              <div className="k">proposals considered</div>
            </div>
          </div>

          <div className="tabs">
            <button className={tab === "confirmed" ? "on" : ""}
                    onClick={() => setTab("confirmed")}>
              Reported ({data.confirmed})
            </button>
            <button className={tab === "retracted" ? "on" : ""}
                    onClick={() => setTab("retracted")}>
              Retracted ({data.retracted})
            </button>
          </div>

          {rows.length === 0 ? (
            <p className="empty">
              {tab === "confirmed" ? "Nothing survived verification." : "Nothing was retracted."}
            </p>
          ) : (
            <table>
              <thead>
                <tr><th>Rule</th><th>Location</th>
                    <th>{tab === "confirmed" ? "Finding" : "Why it was dropped"}</th></tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td className="mono">{row.rule}</td>
                    <td className="loc">{row.path}:{row.line}</td>
                    <td>{tab === "confirmed" ? row.message : row.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2>By rule</h2>
          <table>
            <thead>
              <tr><th>Rule</th><th className="num">Proposed</th>
                  <th className="num">Reported</th><th>Retracted</th></tr>
            </thead>
            <tbody>
              {Object.entries(data.by_rule)
                .sort((a, b) => b[1].proposed - a[1].proposed)
                .map(([rule, v]) => {
                  const rate = 1 - v.confirmed / v.proposed;
                  return (
                    <tr key={rule}>
                      <td className="mono">{rule}</td>
                      <td className="num">{v.proposed}</td>
                      <td className="num">{v.confirmed}</td>
                      <td>
                        <div>{Math.round(rate * 100)}%</div>
                        <div className="bar"><i style={{ width: `${rate * 100}%` }} /></div>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </>
      ) : null}
    </main>
  );
}
