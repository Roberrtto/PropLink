import { useState, useEffect, useCallback } from "react";

const api = (path, method = "GET", body) =>
  fetch("/api" + path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
    .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r.json(); });
const kes = (n) => "KES " + Number(n || 0).toLocaleString();
const pretty = (s) => (s ? new Date(s).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");

function useLoad(path) {
  const [data, setData] = useState(null);
  const load = useCallback(() => api(path).then(setData).catch(() => setData(null)), [path]);
  useEffect(() => { load(); }, [load]);
  return [data, load];
}
const Pill = ({ v, children }) => <span className={"pill " + v}>{children ?? v}</span>;
const Card = ({ title, children }) => <div className="card">{title && <h3>{title}</h3>}{children}</div>;
function Table({ cols, rows, empty = "Nothing here yet." }) {
  if (!rows || !rows.length) return <div className="empty">{empty}</div>;
  return (
    <table><thead><tr>{cols.map((c) => <th key={c.h}>{c.h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={r.id ?? i}>{cols.map((c) => <td key={c.h}>{c.f(r)}</td>)}</tr>)}</tbody></table>
  );
}
function Form({ fields, submit, label, done }) {
  const [v, setV] = useState({});
  return (
    <form className="row" onSubmit={async (e) => { e.preventDefault(); await submit(v); setV({}); done && done(); }}>
      {fields.map((f) => f.options ? (
        <select key={f.k} required value={v[f.k] ?? ""} onChange={(e) => setV({ ...v, [f.k]: e.target.value })}>
          <option value="">{f.p}</option>{f.options.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}</select>
      ) : (
        <input key={f.k} required={!f.optional} type={f.t || "text"} placeholder={f.p} value={v[f.k] ?? ""} onChange={(e) => setV({ ...v, [f.k]: e.target.value })} />
      ))}
      <button className="btn">{label}</button>
    </form>
  );
}

/* ---------------- Pages ---------------- */
function Overview({ pid }) {
  const [o] = useLoad(`/overview?pid=${pid}`); const [rules] = useLoad("/rules");
  if (!o) return <div className="empty">Loading…</div>;
  const text = { overdue_bill: (t) => <>IF a bill is unpaid more than {t} days after its due date<br />THEN mark it Overdue and send a reminder</>,
    stalled_request: (t) => <>IF a request is Assigned and has no update in {t} hours<br />THEN alert the manager</> };
  return (<>
    <div className="grid4">
      <Card><div className="stat"><small>Rent collected</small><b>{kes(o.collected)}</b></div></Card>
      <Card><div className="stat"><small>Outstanding</small><b>{kes(o.outstanding)}</b></div></Card>
      <Card><div className="stat"><small>Occupied units</small><b>{o.occupied} of {o.total_units}</b></div></Card>
      <Card><div className="stat"><small>Open requests</small><b>{o.open_requests}</b></div></Card>
    </div>
    <div className="two">
      <Card title="Recent payments"><Table rows={o.recent} cols={[{ h: "Unit", f: (r) => r.unit }, { h: "Charge", f: (r) => r.charge }, { h: "Amount", f: (r) => r.amount.toLocaleString() }, { h: "Status", f: (r) => <Pill v={r.status} /> }]} empty="No payment requests yet." /></Card>
      <Card title="Automation rules">{(rules || []).filter((r) => r.enabled).map((r) => <div className="rule" key={r.id}>{text[r.kind](r.threshold)}</div>)}</Card>
    </div>
  </>);
}

function Units({ pid, toast }) {
  const [units, load] = useLoad(`/units?pid=${pid}`);
  const vacant = (units || []).filter((u) => u.status === "vacant").map((u) => ({ v: u.id, l: u.number }));
  const all = (units || []).map((u) => ({ v: u.id, l: u.number }));
  const run = (fn, msg) => async (...a) => { try { await fn(...a); toast(msg); load(); } catch (e) { toast(e.message); } };
  return (<>
    <Card title="Units"><Table rows={units} cols={[{ h: "Unit", f: (u) => u.number }, { h: "Block", f: (u) => u.building }, { h: "Rent", f: (u) => kes(u.rent) }, { h: "Status", f: (u) => <Pill v={u.status === "occupied" ? "paid" : "pending"}>{u.status}</Pill> },
      { h: "Resident", f: (u) => u.resident || "—" }, { h: "", f: (u) => u.tenancy_id && <button className="btn sm red" onClick={run(() => api(`/tenancies/${u.tenancy_id}/end`, "POST"), "Tenancy ended")}>End tenancy</button> }]} /></Card>
    <Card title="Add a unit"><Form label="Add unit" fields={[{ k: "building", p: "Block (e.g. B)" }, { k: "number", p: "Unit number" }, { k: "rent", p: "Monthly rent", t: "number" }]}
      submit={run((v) => api("/units", "POST", { ...v, rent: +v.rent, property_id: pid }), "Unit added")} /></Card>
    <Card title="Assign a resident to a vacant unit"><Form label="Assign" fields={[{ k: "unit_id", p: "Vacant unit", options: vacant }, { k: "full_name", p: "Full name" }, { k: "phone", p: "Phone (07…)" }]}
      submit={run((v) => api("/tenancies", "POST", { ...v, unit_id: +v.unit_id }), "Resident assigned")} /></Card>
    <Card title="Record a water meter reading"><Form label="Save reading" fields={[{ k: "unit_id", p: "Unit", options: all }, { k: "value", p: "Meter value", t: "number" }]}
      submit={run((v) => api("/meter-readings", "POST", { unit_id: +v.unit_id, value: +v.value }), "Reading saved")} /></Card>
  </>);
}

function Billing({ pid, toast }) {
  const [cfg, loadC] = useLoad(`/billing-configs?pid=${pid}`); const [bills, loadB] = useLoad(`/bills?pid=${pid}`);
  const safe = (fn, msg) => async (...a) => { try { await fn(...a); toast(msg); loadC(); loadB(); } catch (e) { toast(e.message); } };
  return (<>
    <Card title="Billing rules for this property">
      <Table rows={cfg} cols={[{ h: "Charge", f: (c) => c.charge_type }, { h: "Method", f: (c) => ({ rent: "Unit rent", fixed: "Fixed amount", metered: "Per meter unit" })[c.method] },
        { h: "Rate", f: (c) => (c.method === "rent" ? "per unit" : kes(c.rate)) }, { h: "Due day", f: (c) => c.due_day }, { h: "", f: (c) => <button className="btn sm red" onClick={safe(() => api(`/billing-configs/${c.id}`, "DELETE"), "Rule removed")}>Remove</button> }]} />
      <Form label="Add rule" fields={[{ k: "charge_type", p: "Charge (e.g. Parking)" }, { k: "method", p: "Method", options: [{ v: "fixed", l: "Fixed amount" }, { v: "metered", l: "Per meter unit" }, { v: "rent", l: "Unit rent" }] }, { k: "rate", p: "Rate (KES)", t: "number", optional: true }, { k: "due_day", p: "Due day", t: "number", optional: true }]}
        submit={safe((v) => api("/billing-configs", "POST", { property_id: pid, charge_type: v.charge_type, method: v.method, rate: +(v.rate || 0), due_day: +(v.due_day || 5) }), "Rule added")} />
    </Card>
    <Card title="Bills"><Table rows={bills} cols={[{ h: "Unit", f: (b) => b.unit }, { h: "Resident", f: (b) => b.resident }, { h: "Charge", f: (b) => b.charge_type }, { h: "Period", f: (b) => b.period }, { h: "Amount", f: (b) => b.amount.toLocaleString() }, { h: "Due", f: (b) => b.due_date }, { h: "Status", f: (b) => <Pill v={b.status} /> },
      { h: "", f: (b) => b.status !== "paid" && <button className="btn sm ghost" onClick={safe(() => api("/payments/stk", "POST", { bill_id: b.id }), "Payment request sent. Bill stays Pending until confirmed.")}>Request payment</button> }]} empty="No bills yet. Press Generate bills." /></Card>
  </>);
}

function Payments({ pid, toast }) {
  const [rows, load] = useLoad(`/payments?pid=${pid}`);
  const sim = (id, o) => async () => { try { await api(`/mock/daraja/${id}/${o}`, "POST"); toast(o === "success" ? "Payment confirmed" : "Payment failed"); load(); } catch (e) { toast(e.message); } };
  return (<Card title="Payment requests and confirmed transactions">
    <Table rows={rows} cols={[{ h: "Unit", f: (r) => r.unit }, { h: "Resident", f: (r) => r.resident }, { h: "Charge", f: (r) => `${r.charge} ${r.period}` }, { h: "Amount", f: (r) => r.amount.toLocaleString() }, { h: "Phone", f: (r) => r.phone },
      { h: "Status", f: (r) => <Pill v={r.status} /> }, { h: "M-Pesa receipt", f: (r) => r.mpesa_receipt || "—" }, { h: "System receipt", f: (r) => r.receipt || "—" }, { h: "Sent", f: (r) => pretty(r.created_at) },
      { h: "Daraja simulator", f: (r) => r.status === "pending" && <><button className="btn sm" onClick={sim(r.checkout_request_id, "success")}>Confirm</button> <button className="btn sm red" onClick={sim(r.checkout_request_id, "fail")}>Fail</button></> }]} empty="No payment requests yet. Request one from Billing." />
  </Card>);
}

function Maintenance({ pid, toast }) {
  const [reqs, load] = useLoad(`/requests?pid=${pid}`); const [provs] = useLoad("/providers"); const [units] = useLoad(`/units?pid=${pid}`);
  const go = (fn, msg) => async () => { try { await fn(); toast(msg); load(); } catch (e) { toast(e.message); } };
  const patch = (id, b, msg) => go(() => api(`/requests/${id}`, "PATCH", b), msg);
  const [cost, setCost] = useState({});
  return (<>
    <Card title="Service requests"><Table rows={reqs} cols={[{ h: "#", f: (r) => r.id }, { h: "Unit", f: (r) => r.unit }, { h: "Issue", f: (r) => `${r.category}: ${r.title}` }, { h: "Status", f: (r) => <Pill v={r.status} /> },
      { h: "Provider", f: (r) => <select value={r.provider_id || ""} onChange={(e) => patch(r.id, { provider_id: +e.target.value }, "Provider assigned")()}><option value="">Assign…</option>{(provs || []).filter((p) => p.approved).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select> },
      { h: "Progress", f: (r) => <select value={r.status} onChange={(e) => patch(r.id, { status: e.target.value }, "Status updated")()}>{["Submitted", "Assigned", "In Progress", "Completed"].map((s) => <option key={s}>{s}</option>)}</select> },
      { h: "Cost (KES)", f: (r) => <input style={{ width: 90 }} type="number" defaultValue={r.cost || ""} onChange={(e) => setCost({ ...cost, [r.id]: +e.target.value })} onBlur={() => cost[r.id] != null && patch(r.id, { cost: cost[r.id] }, "Cost saved")()} /> },
      { h: "", f: (r) => r.cost > 0 && <button className="btn sm ghost" onClick={go(() => api(`/requests/${r.id}/charge`, "POST"), "Charge added to resident's bills")}>Bill resident</button> }]} empty="No service requests." /></Card>
    <Card title="Log a request for a resident"><Form label="Log request" fields={[{ k: "unit_id", p: "Unit", options: (units || []).filter((u) => u.tenancy_id).map((u) => ({ v: u.id, l: u.number })) }, { k: "category", p: "Category (Plumbing…)" }, { k: "title", p: "What is wrong?" }]}
      submit={async (v) => { try { await api("/requests", "POST", { ...v, unit_id: +v.unit_id, property_id: pid }); toast("Request logged"); load(); } catch (e) { toast(e.message); } }} /></Card>
  </>);
}

function Providers({ toast }) {
  const [rows, load] = useLoad("/providers");
  return (<>
    <Card title="Service providers"><Table rows={rows} cols={[{ h: "Name", f: (p) => p.name }, { h: "Category", f: (p) => p.category }, { h: "Phone", f: (p) => p.phone }, { h: "Approved", f: (p) => <Pill v={p.approved ? "paid" : "failed"}>{p.approved ? "Approved" : "Suspended"}</Pill> },
      { h: "", f: (p) => <button className="btn sm ghost" onClick={async () => { await api(`/providers/${p.id}/toggle`, "POST"); load(); }}>{p.approved ? "Suspend" : "Approve"}</button> }]} /></Card>
    <Card title="Add a provider"><Form label="Add provider" fields={[{ k: "name", p: "Business name" }, { k: "category", p: "Category" }, { k: "phone", p: "Phone" }]} submit={async (v) => { await api("/providers", "POST", v); toast("Provider added"); load(); }} /></Card>
  </>);
}

function Reports({ pid }) {
  const [r] = useLoad(`/reports?pid=${pid}`); const [audit] = useLoad("/audit");
  if (!r) return <div className="empty">Loading…</div>;
  const Bars = ({ title, rows }) => { const max = Math.max(1, ...rows.map((x) => x.value)); return (<Card title={title}>{rows.length ? rows.map((x) => (
    <div key={x.label} style={{ marginBottom: 10 }}><div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}><span>{x.label}</span><b>{kes(x.value)}</b></div><div className="bar" style={{ width: `${(x.value / max) * 100}%` }} /></div>)) : <div className="empty">No data yet.</div>}</Card>); };
  return (<>
    <div className="grid4"><Bars title="Collected by charge" rows={r.collected} /><Bars title="Outstanding by charge" rows={r.outstanding} /><Bars title="Maintenance spend by category" rows={r.maintenance} /></div>
    <Card title={`Unresolved service requests: ${r.unresolved}`} />
    <Card title="Audit log"><Table rows={audit} cols={[{ h: "When", f: (a) => pretty(a.at) }, { h: "Who", f: (a) => a.actor }, { h: "Action", f: (a) => a.action }, { h: "Record", f: (a) => `${a.entity}${a.entity_id ? " #" + a.entity_id : ""}` }]} /></Card>
  </>);
}

function Automation({ toast }) {
  const [rules, load] = useLoad("/rules"); const [log, setLog] = useState(null);
  const label = { overdue_bill: ["Days after due date before a bill is marked Overdue", "days"], stalled_request: ["Hours without an update before the manager is alerted", "hours"] };
  return (<>
    <Card title="Automation rules">{(rules || []).map((r) => (
      <div className="rule" key={r.id} style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ flex: 1, minWidth: 220 }}>{label[r.kind][0]}</span>
        <input style={{ width: 80 }} type="number" defaultValue={r.threshold} onBlur={async (e) => { await api(`/rules/${r.id}`, "PATCH", { threshold: +e.target.value }); toast("Rule saved"); }} /> {label[r.kind][1]}
        <button className={"btn sm " + (r.enabled ? "" : "red")} onClick={async () => { await api(`/rules/${r.id}`, "PATCH", { enabled: !r.enabled }); load(); }}>{r.enabled ? "On" : "Off"}</button>
      </div>))}
      <button className="btn" onClick={async () => setLog((await api("/automation/run", "POST")).actions)}>Run rules now</button></Card>
    {log && <Card title="Last run">{log.length ? log.map((l, i) => <div className="rule" key={i}>{l}</div>) : <div className="empty">No actions needed.</div>}</Card>}
  </>);
}

/* ---------------- Shell ---------------- */
const NAV = ["Overview", "Properties and units", "Billing", "Payments", "Maintenance", "Providers", "Reports", "Automation rules"];
export default function App() {
  const [page, setPage] = useState("Overview"); const [props] = useLoad("/properties"); const [msg, setMsg] = useState(""); const [tick, setTick] = useState(0); const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const toast = (m) => { setMsg(m); setTimeout(() => setMsg(""), 3500); setTick((t) => t + 1); };
  const prop = props && props[0]; if (!prop) return <div className="main"><div className="empty">Connecting to the PropLink API… (is the backend running on port 8000?)</div></div>;
  const pid = prop.id; const P = { pid, toast };
  const body = { Overview: <Overview {...P} />, "Properties and units": <Units {...P} />, Billing: <Billing {...P} />, Payments: <Payments {...P} />, Maintenance: <Maintenance {...P} />, Providers: <Providers {...P} />, Reports: <Reports {...P} />, "Automation rules": <Automation {...P} /> }[page];
  return (
    <div className="app">
      <nav className="side"><h1>PropLink</h1>{NAV.map((n) => <button key={n} className={n === page ? "on" : ""} onClick={() => setPage(n)}>{n}</button>)}</nav>
      <main className="main">
        <div className="head"><div><small>{prop.name}</small><h2>{page}</h2></div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />
            <button className="btn" onClick={async () => { try { const r = await api("/bills/generate", "POST", { property_id: pid, period }); toast(`${r.created} bills generated for ${r.period}`); } catch (e) { toast(e.message); } }}>Generate bills</button>
          </div></div>
        <div key={page + tick}>{body}</div>
      </main>
      {msg && <div className="toast">{msg}</div>}
    </div>
  );
}
