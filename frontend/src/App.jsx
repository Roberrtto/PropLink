import { useState, useEffect, useCallback } from "react";

// The sign-in token lives only for this browser tab (sessionStorage) and is sent with every request.
const TOKEN_KEY = "proplink_token";
const getToken = () => { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } };
const setToken = (t) => { try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ } };
const api = (path, method = "GET", body) => {
  const headers = { "Content-Type": "application/json" };
  const t = getToken(); if (t) headers.Authorization = "Bearer " + t;
  return fetch("/api" + path, { method, headers, body: body ? JSON.stringify(body) : undefined })
    .then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (r.status === 401 && t) { setToken(null); window.dispatchEvent(new Event("proplink-signed-out")); }
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : r.status === 422 ? "Please check the values you entered" : r.statusText);
      return data;
    });
};
const kes = (n) => "KES " + Number(n || 0).toLocaleString();
const pretty = (s) => (s ? new Date(s).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, x]) => x !== "" && x != null));

function useLoad(path) {
  const [data, setData] = useState(null);
  const load = useCallback(() => (path ? api(path).then(setData).catch(() => setData(null)) : Promise.resolve()), [path]);
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
// A submit handler can return false to keep what the person typed (for example after an error).
function Form({ fields, submit, label, done }) {
  const [v, setV] = useState({});
  return (
    <form className="row" onSubmit={async (e) => { e.preventDefault(); const ok = await submit(v); if (ok !== false) { setV({}); done && done(); } }}>
      {fields.map((f) => f.options ? (
        <select key={f.k} required={!f.optional} value={v[f.k] ?? ""} onChange={(e) => setV({ ...v, [f.k]: e.target.value })}>
          <option value="">{f.p}</option>{f.options.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}</select>
      ) : (
        <input key={f.k} required={!f.optional} type={f.t || "text"} placeholder={f.p} title={f.p} value={v[f.k] ?? ""} onChange={(e) => setV({ ...v, [f.k]: e.target.value })} />
      ))}
      <button className="btn">{label}</button>
    </form>
  );
}

/* ---------------- Pages ---------------- */
function Overview({ pid, me }) {
  const [o] = useLoad(`/overview?pid=${pid}`); const [rules] = useLoad("/rules");
  if (!o) return <div className="empty">Loading…</div>;
  const landlord = me.role === "landlord";
  const text = { overdue_bill: (t) => <>IF a bill is unpaid more than {t} days after its due date<br />THEN mark it Overdue and send a reminder</>,
    stalled_request: (t) => <>IF a request is Assigned and has no update in {t} hours<br />THEN alert the staff</> };
  return (<>
    <div className="grid4">
      {landlord && <Card><div className="stat"><small>Rent collected</small><b>{kes(o.collected)}</b></div></Card>}
      <Card><div className="stat"><small>Outstanding</small><b>{kes(o.outstanding)}</b></div></Card>
      <Card><div className="stat"><small>Occupied units</small><b>{o.occupied} of {o.total_units}</b></div></Card>
      <Card><div className="stat"><small>Open requests</small><b>{o.open_requests}</b></div></Card>
    </div>
    <div className={landlord ? "two" : ""}>
      {landlord && <Card title="Recent payments"><Table rows={o.recent} cols={[{ h: "Unit", f: (r) => r.unit }, { h: "Charge", f: (r) => r.charge }, { h: "Amount", f: (r) => r.amount.toLocaleString() }, { h: "Status", f: (r) => <Pill v={r.status} /> }]} empty="No payment requests yet." /></Card>}
      <Card title="Automation rules">{(rules || []).filter((r) => r.enabled).map((r) => <div className="rule" key={r.id}>{text[r.kind](r.threshold)}</div>)}</Card>
    </div>
  </>);
}

function Units({ pid, toast, me, reloadProps }) {
  const landlord = me.role === "landlord";
  const [units, load] = useLoad(`/units?pid=${pid}`);
  const all = (units || []).map((u) => ({ v: u.id, l: u.number }));
  const run = (fn, msg) => async (...a) => { try { await fn(...a); toast(msg); load(); } catch (e) { toast(e.message); return false; } };
  return (<>
    <Card title="Units"><Table rows={units} cols={[{ h: "Unit", f: (u) => u.number }, { h: "Block", f: (u) => u.building }, { h: "Rent", f: (u) => kes(u.rent) }, { h: "Status", f: (u) => <Pill v={u.status === "occupied" ? "paid" : "pending"}>{u.status}</Pill> },
      { h: "Resident", f: (u) => u.resident || "—" }]} /></Card>
    {landlord && <Card title="Add a unit"><Form label="Add unit" fields={[{ k: "building", p: "Block (e.g. B)" }, { k: "number", p: "Unit number" }, { k: "rent", p: "Monthly rent", t: "number" }]}
      submit={run((v) => api("/units", "POST", { ...v, rent: +v.rent, property_id: pid }), "Unit added")} /></Card>}
    <Card title="Record a water meter reading"><Form label="Save reading" fields={[{ k: "unit_id", p: "Unit", options: all }, { k: "value", p: "Meter value", t: "number" }]}
      submit={run((v) => api("/meter-readings", "POST", { unit_id: +v.unit_id, value: +v.value }), "Reading saved")} /></Card>
    {landlord && <Card title="Add another property"><Form label="Add property" fields={[{ k: "name", p: "Property name" }, { k: "address", p: "Address" }]}
      submit={async (v) => { try { await api("/properties", "POST", v); toast("Property added. Pick it from the list at the top."); reloadProps(); } catch (e) { toast(e.message); return false; } }} /></Card>}
    <div className="empty">To register, move or remove a resident, use the Residents page.</div>
  </>);
}

function Residents({ pid, toast }) {
  const [rows, load] = useLoad(`/residents?pid=${pid}`); const [units, loadUnits] = useLoad(`/units?pid=${pid}`);
  const [sel, setSel] = useState(null); const [d, setD] = useState(null); const [code, setCode] = useState(null); const [left, setLeft] = useState(0);
  useEffect(() => { if (sel) api(`/residents/${sel}`).then(setD).catch(() => setD(null)); else setD(null); }, [sel, rows]);
  useEffect(() => {
    if (!code) return;
    const t = setInterval(() => setLeft(Math.max(0, Math.round((code.until - Date.now()) / 1000))), 500);
    return () => clearInterval(t);
  }, [code]);
  const refresh = () => { load(); loadUnits(); };
  const act = (fn, msg) => async (v) => { try { await fn(v); toast(msg); refresh(); } catch (e) { toast(e.message); return false; } };
  const vacant = (units || []).filter((u) => u.status === "vacant").map((u) => ({ v: u.id, l: `${u.building}${u.number} (${kes(u.rent)})` }));
  const issue = async () => {
    try { const r = await api(`/tenancies/${d.tenancy_id}/activation-code`, "POST"); setCode({ code: r.code, until: Date.now() + r.expires_in_seconds * 1000 }); setLeft(r.expires_in_seconds); }
    catch (e) { toast(e.message); }
  };
  return (<>
    <Card title="Residents"><Table rows={rows} cols={[{ h: "Name", f: (r) => r.name }, { h: "Unit", f: (r) => r.building + r.unit }, { h: "Phone", f: (r) => r.phone },
      { h: "Owes", f: (r) => kes(r.balance) }, { h: "Open requests", f: (r) => r.open_requests },
      { h: "", f: (r) => <button className="btn sm ghost" onClick={() => { setSel(r.resident_id); setCode(null); }}>View</button> }]} empty="No residents yet. Register one below." /></Card>
    {d && <Card title={`${d.name} · ${d.building}${d.unit}`}>
      <div className="rule">{d.id_type === "passport" ? "Passport" : "National ID"}: {d.id_number} · Born {d.date_of_birth} · Phone {d.phone}{d.email ? ` · ${d.email}` : ""}<br />
        Guardian: {d.guardian_name ? `${d.guardian_name} (${d.guardian_phone})` : "—"} · Since {d.since} · Owes {kes(d.balance)}</div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0" }}>
        <button className="btn sm" onClick={issue}>Issue activation code</button>
        <button className="btn sm red" onClick={async () => {
          if (!window.confirm(`Remove ${d.name}? Their tenancy ends and they are signed out of the app.`)) return;
          const ok = await act(() => api(`/tenancies/${d.tenancy_id}/end`, "POST"), "Resident removed")();
          if (ok !== false) { setSel(null); setD(null); setCode(null); }
        }}>Remove resident (moved out)</button>
      </div>
      {code && <div className="rule">{left > 0 ? <>Code: <b style={{ fontSize: 24, letterSpacing: 4 }}>{code.code}</b> · expires in {left}s. Give it to the resident now.</> : "Code expired. Issue a new one."}</div>}
      <h3 style={{ marginTop: 16 }}>Move to another unit in this building</h3>
      <Form label="Move" fields={[{ k: "unit_id", p: "Vacant unit", options: (units || []).filter((u) => u.status === "vacant" && u.building === d.building).map((u) => ({ v: u.id, l: u.number })) }]}
        submit={act((v) => api(`/tenancies/${d.tenancy_id}/transfer`, "POST", { unit_id: +v.unit_id }), "Resident moved")} />
      <h3 style={{ marginTop: 16 }}>Edit details (fill in only what changes)</h3>
      <Form label="Save changes" fields={[{ k: "full_name", p: "Full name", optional: true }, { k: "date_of_birth", p: "Date of birth", t: "date", optional: true },
        { k: "id_number", p: "ID / passport number", optional: true }, { k: "phone", p: "Phone", t: "tel", optional: true }, { k: "email", p: "Email", t: "email", optional: true },
        { k: "guardian_name", p: "Guardian name", optional: true }, { k: "guardian_phone", p: "Guardian phone", t: "tel", optional: true }]}
        submit={act((v) => api(`/residents/${d.resident_id}`, "PATCH", clean(v)), "Details saved")} />
      <h3 style={{ marginTop: 16 }}>What they owe</h3>
      <Table rows={d.bills} cols={[{ h: "Charge", f: (b) => b.charge_type }, { h: "Period", f: (b) => b.period }, { h: "Amount", f: (b) => kes(b.amount) }, { h: "Due", f: (b) => b.due_date }, { h: "Status", f: (b) => <Pill v={b.status} /> }]} empty="No bills." />
      <h3 style={{ marginTop: 16 }}>Service requests</h3>
      <Table rows={d.requests} cols={[{ h: "Issue", f: (r) => `${r.category}: ${r.title}` }, { h: "Status", f: (r) => <Pill v={r.status} /> }]} empty="No requests." />
    </Card>}
    <Card title="Register a new resident"><Form label="Register" fields={[
      { k: "full_name", p: "Full name" }, { k: "date_of_birth", p: "Date of birth", t: "date" },
      { k: "id_type", p: "ID type", options: [{ v: "national_id", l: "National ID" }, { v: "passport", l: "Passport" }] }, { k: "id_number", p: "ID / passport number" },
      { k: "phone", p: "Phone (0712 345 678)", t: "tel" }, { k: "email", p: "Email (optional)", t: "email", optional: true },
      { k: "guardian_name", p: "Parent/guardian name (required under 18)", optional: true }, { k: "guardian_phone", p: "Guardian phone", t: "tel", optional: true },
      { k: "unit_id", p: "Unit", options: vacant }]}
      submit={act((v) => api("/residents", "POST", { ...clean(v), unit_id: +v.unit_id }), "Resident registered. Issue an activation code when they are ready to sign in.")} /></Card>
  </>);
}

function Billing({ pid, toast, me }) {
  const landlord = me.role === "landlord";
  const [cfg, loadC] = useLoad(`/billing-configs?pid=${pid}`); const [bills, loadB] = useLoad(`/bills?pid=${pid}`);
  const safe = (fn, msg) => async (...a) => { try { await fn(...a); toast(msg); loadC(); loadB(); } catch (e) { toast(e.message); return false; } };
  return (<>
    <Card title="Billing rules for this property">
      <Table rows={cfg} cols={[{ h: "Charge", f: (c) => c.charge_type }, { h: "Method", f: (c) => ({ rent: "Unit rent", fixed: "Fixed amount", metered: "Per meter unit" })[c.method] },
        { h: "Rate", f: (c) => (c.method === "rent" ? "per unit" : kes(c.rate)) }, { h: "Due day", f: (c) => c.due_day },
        ...(landlord ? [{ h: "", f: (c) => <button className="btn sm red" onClick={safe(() => api(`/billing-configs/${c.id}`, "DELETE"), "Rule removed")}>Remove</button> }] : [])]} />
      {landlord && <Form label="Add rule" fields={[{ k: "charge_type", p: "Charge (e.g. Parking)" }, { k: "method", p: "Method", options: [{ v: "fixed", l: "Fixed amount" }, { v: "metered", l: "Per meter unit" }, { v: "rent", l: "Unit rent" }] }, { k: "rate", p: "Rate (KES)", t: "number", optional: true }, { k: "due_day", p: "Due day", t: "number", optional: true }]}
        submit={safe((v) => api("/billing-configs", "POST", { property_id: pid, charge_type: v.charge_type, method: v.method, rate: +(v.rate || 0), due_day: +(v.due_day || 5) }), "Rule added")} />}
    </Card>
    <Card title="Post one charge to many units at once">
      <Form label="Post charge" fields={[
        { k: "charge_type", p: "Charge (e.g. Garbage)" }, { k: "amount", p: "Amount per unit (KES)", t: "number" },
        { k: "period", p: "Month", t: "month" }, { k: "due_date", p: "Due date", t: "date" },
        { k: "scope", p: "Applies to", options: [{ v: "all", l: "All occupied units" }, { v: "building", l: "One building" }, { v: "rent", l: "Units with the same rent" }] },
        { k: "building", p: "Block (if one building)", optional: true }, { k: "rent", p: "Rent amount (if same rent)", t: "number", optional: true }]}
        submit={async (v) => {
          if (v.scope === "building" && !v.building) { toast("Enter the block"); return false; }
          if (v.scope === "rent" && !v.rent) { toast("Enter the rent amount"); return false; }
          try {
            const r = await api("/charges/bulk", "POST", { property_id: pid, charge_type: v.charge_type, amount: +v.amount, period: v.period, due_date: v.due_date,
              building: v.scope === "building" ? v.building : null, rent: v.scope === "rent" ? +v.rent : null });
            toast(`${r.created} bills posted, ${r.skipped} skipped (already billed)`); loadB();
          } catch (e) { toast(e.message); return false; }
        }} />
    </Card>
    <Card title="Bills"><Table rows={bills} cols={[{ h: "Unit", f: (b) => b.unit }, { h: "Resident", f: (b) => b.resident }, { h: "Charge", f: (b) => b.charge_type }, { h: "Period", f: (b) => b.period }, { h: "Amount", f: (b) => b.amount.toLocaleString() }, { h: "Due", f: (b) => b.due_date }, { h: "Status", f: (b) => <Pill v={b.status} /> },
      ...(landlord ? [{ h: "", f: (b) => b.status !== "paid" && <button className="btn sm ghost" onClick={safe(() => api("/payments/stk", "POST", { bill_id: b.id }), "Payment request sent. Bill stays Pending until confirmed.")}>Request payment</button> }] : [])]} empty="No bills yet. Press Generate bills." /></Card>
  </>);
}

function Payments({ pid, toast, simulated }) {
  const [rows, load] = useLoad(`/payments?pid=${pid}`);
  const sim = (id, o) => async () => { try { await api(`/mock/daraja/${id}/${o}`, "POST"); toast(o === "success" ? "Payment confirmed" : "Payment failed"); load(); } catch (e) { toast(e.message); } };
  return (<Card title="Payment requests and confirmed transactions">
    <Table rows={rows} cols={[{ h: "Unit", f: (r) => r.unit }, { h: "Resident", f: (r) => r.resident }, { h: "Charge", f: (r) => `${r.charge} ${r.period}` }, { h: "Amount", f: (r) => r.amount.toLocaleString() }, { h: "Phone", f: (r) => r.phone },
      { h: "Status", f: (r) => <Pill v={r.status} /> }, { h: "M-Pesa receipt", f: (r) => r.mpesa_receipt || "—" }, { h: "System receipt", f: (r) => r.receipt || "—" }, { h: "Sent", f: (r) => pretty(r.created_at) },
      ...(simulated ? [{ h: "Daraja simulator", f: (r) => r.status === "pending" && <><button className="btn sm" onClick={sim(r.checkout_request_id, "success")}>Confirm</button> <button className="btn sm red" onClick={sim(r.checkout_request_id, "fail")}>Fail</button></> }] : [])]} empty="No payment requests yet. Request one from Billing." />
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
      { h: "", f: (r) => r.cost > 0 && <button className="btn sm ghost" onClick={go(() => api(`/requests/${r.id}/charge`, "POST"), "Charge added to resident's bills")}>Bill resident</button> },
      { h: "", f: (r) => r.status !== "Completed" && <button className="btn sm" onClick={go(() => api(`/requests/${r.id}/clear`, "POST"), "Request cleared")}>Clear (resident satisfied)</button> }]} empty="No service requests." /></Card>
    <Card title="Log a request for a resident"><Form label="Log request" fields={[{ k: "unit_id", p: "Unit", options: (units || []).filter((u) => u.tenancy_id).map((u) => ({ v: u.id, l: u.number })) }, { k: "category", p: "Category (Plumbing…)" }, { k: "title", p: "What is wrong?" }]}
      submit={async (v) => { try { await api("/requests", "POST", { ...v, unit_id: +v.unit_id, property_id: pid }); toast("Request logged"); load(); } catch (e) { toast(e.message); return false; } }} /></Card>
  </>);
}

function Providers({ toast, me }) {
  const landlord = me.role === "landlord";
  const [rows, load] = useLoad("/providers");
  return (<>
    <Card title="Service providers"><Table rows={rows} cols={[{ h: "Name", f: (p) => p.name }, { h: "Category", f: (p) => p.category }, { h: "Phone", f: (p) => p.phone }, { h: "Approved", f: (p) => <Pill v={p.approved ? "paid" : "failed"}>{p.approved ? "Approved" : "Suspended"}</Pill> },
      ...(landlord ? [{ h: "", f: (p) => <button className="btn sm ghost" onClick={async () => { await api(`/providers/${p.id}/toggle`, "POST"); load(); }}>{p.approved ? "Suspend" : "Approve"}</button> }] : [])]} /></Card>
    {landlord && <Card title="Add a provider"><Form label="Add provider" fields={[{ k: "name", p: "Business name" }, { k: "category", p: "Category" }, { k: "phone", p: "Phone (0712 345 678)", t: "tel" }]} submit={async (v) => { try { await api("/providers", "POST", v); toast("Provider added"); load(); } catch (e) { toast(e.message); return false; } }} /></Card>}
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
    <Card title="Audit log"><Table rows={audit} cols={[{ h: "When", f: (a) => pretty(a.at) }, { h: "Who", f: (a) => a.actor }, { h: "Action", f: (a) => a.action }, { h: "Record", f: (a) => `${a.entity}${a.entity_id ? " #" + a.entity_id : ""}` }, { h: "Details", f: (a) => a.details || "—" }]} /></Card>
  </>);
}

function Automation({ toast }) {
  const [rules, load] = useLoad("/rules"); const [log, setLog] = useState(null);
  const label = { overdue_bill: ["Days after due date before a bill is marked Overdue", "days"], stalled_request: ["Hours without an update before staff are alerted", "hours"] };
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

function PaymentSettings({ toast }) {
  const [a, load] = useLoad("/payment-account");
  if (!a) return <div className="empty">Loading…</div>;
  return (<>
    <Card title="Where your rent money goes">
      <div className="rule">
        {a.simulated ? "Test mode: payments are simulated, so no real money moves and these details are not used yet." : a.configured ? "Live: residents pay into the account below." : "Not set up: residents cannot pay by M-Pesa until you complete the details below."}<br />
        Your M-Pesa credentials are stored encrypted and are never shown again. Leave a secret blank to keep the one already saved.
      </div>
      <Form label="Save payment details" fields={[
        { k: "tx_type", p: "Account type", options: [{ v: "paybill", l: "Paybill" }, { v: "till", l: "Till (Buy Goods)" }] },
        { k: "shortcode", p: `Business shortcode${a.shortcode ? ` (now ${a.shortcode})` : ""}` },
        { k: "party_b", p: `Till number (tills only${a.party_b ? `, now ${a.party_b}` : ""})`, optional: true },
        { k: "consumer_key", p: a.has_key ? "Consumer key (saved, blank keeps it)" : "Consumer key", optional: a.has_key },
        { k: "consumer_secret", p: a.has_secret ? "Consumer secret (saved, blank keeps it)" : "Consumer secret", t: "password", optional: a.has_secret },
        { k: "passkey", p: a.has_passkey ? "Passkey (saved, blank keeps it)" : "Passkey", t: "password", optional: a.has_passkey }]}
        submit={async (v) => { try { await api("/payment-account", "POST", clean(v)); toast("Payment details saved"); load(); } catch (e) { toast(e.message); return false; } }} />
    </Card>
    <Card title="Send yourself a KES 1 test">
      <div className="empty">Sends a payment prompt to your own phone so you can check the details work.</div>
      <Form label="Send test" fields={[{ k: "phone", p: "Your phone (0712 345 678)", t: "tel" }]}
        submit={async (v) => { try { const r = await api("/payment-account/test", "POST", v); toast(r.simulated ? "Simulated test sent (test mode)" : "Prompt sent. Check your phone."); } catch (e) { toast(e.message); return false; } }} />
    </Card>
  </>);
}

function Staff({ toast, me }) {
  const landlord = me.role === "landlord";
  const [rows, load] = useLoad(landlord ? "/staff" : null); const [props] = useLoad(landlord ? "/properties" : null);
  const [sel, setSel] = useState(null); const [picked, setPicked] = useState([]);
  const run = (fn, msg) => async (...a) => { try { await fn(...a); toast(msg); load(); } catch (e) { toast(e.message); return false; } };
  const names = (s) => s.role === "landlord" ? "All" : ((props || []).filter((p) => (s.property_ids || []).includes(p.id)).map((p) => p.name).join(", ") || "None yet");
  const person = (rows || []).find((s) => s.id === sel);
  return (<>
    <Card title="Change your password"><Form label="Change password" fields={[{ k: "current_password", p: "Current password", t: "password" }, { k: "new_password", p: "New password (10+ chars, Aa1)", t: "password" }]}
      submit={run(async (v) => { const r = await api("/staff/me/password", "POST", v); setToken(r.token); }, "Password changed. Other devices have been signed out.")} /></Card>
    {landlord && <>
      <Card title="Landlords and managers"><Table rows={rows} cols={[{ h: "Name", f: (s) => s.full_name }, { h: "Email", f: (s) => s.email }, { h: "Role", f: (s) => s.role },
        { h: "Properties", f: (s) => names(s) },
        { h: "Status", f: (s) => <Pill v={s.active ? "paid" : "failed"}>{s.active ? "Active" : "Disabled"}</Pill> }, { h: "Last sign-in", f: (s) => pretty(s.last_login) || "Never" },
        { h: "", f: (s) => s.role === "manager" && <button className="btn sm ghost" onClick={() => { setSel(s.id); setPicked(s.property_ids || []); }}>Properties</button> },
        { h: "", f: (s) => s.id !== me.id && <button className="btn sm ghost" onClick={run(() => api(`/staff/${s.id}`, "PATCH", { active: !s.active }), "Account updated")}>{s.active ? "Disable" : "Enable"}</button> }]} /></Card>
      {person && <Card title={`Properties ${person.full_name} can see`}>
        {(props || []).map((p) => (
          <label key={p.id} style={{ display: "block", margin: "6px 0" }}>
            <input type="checkbox" checked={picked.includes(p.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, p.id] : picked.filter((x) => x !== p.id))} /> {p.name}
          </label>))}
        <button className="btn" onClick={async () => { await run(() => api(`/staff/${person.id}`, "PATCH", { property_ids: picked }), "Saved. They will need to sign in again.")(); setSel(null); }}>Save</button>
      </Card>}
      <Card title="Add a landlord or manager"><Form label="Create account" fields={[{ k: "full_name", p: "Full name" }, { k: "email", p: "Email", t: "email" }, { k: "role", p: "Role", options: [{ v: "manager", l: "Manager (sees only the properties you assign)" }, { v: "landlord", l: "Landlord (full access to everything)" }] }, { k: "password", p: "Temporary password (10+ chars, Aa1)", t: "password" }]}
        submit={run((v) => api("/staff", "POST", v), "Account created. Assign properties to a manager with the Properties button. Share the temporary password privately.")} /></Card>
    </>}
  </>);
}

function Login({ onDone }) {
  const [v, setV] = useState({ email: "", password: "" }); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    try { const r = await api("/staff/login", "POST", v); setToken(r.token); onDone(r.user); } catch (e2) { setErr(e2.message); }
    setBusy(false);
  };
  return (
    <div className="main" style={{ maxWidth: 380, margin: "10vh auto" }}>
      <Card title="Sign in to PropLink">
        <form onSubmit={submit} style={{ display: "grid", gap: 10 }}>
          <input type="email" autoComplete="username" required placeholder="Email" value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} />
          <input type="password" autoComplete="current-password" required placeholder="Password" value={v.password} onChange={(e) => setV({ ...v, password: e.target.value })} />
          {err && <div style={{ color: "#b42323" }}>{err}</div>}
          <button className="btn" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </Card>
    </div>
  );
}

function FirstProperty({ me, onCreated, toast }) {
  if (me.role !== "landlord") return <div className="main"><div className="empty">No property has been assigned to you yet. Ask your landlord to assign one.</div></div>;
  return (
    <div className="main" style={{ maxWidth: 560, margin: "8vh auto" }}>
      <Card title="Create your first property">
        <Form label="Create property" fields={[{ k: "name", p: "Property name (e.g. Riverside Court)" }, { k: "address", p: "Address (e.g. Ngong Road, Nairobi)" }]}
          submit={async (v) => { try { await api("/properties", "POST", v); onCreated(); } catch (e) { toast(e.message); return false; } }} />
      </Card>
    </div>
  );
}

/* ---------------- Shell ---------------- */
const LANDLORD_NAV = ["Overview", "Properties and units", "Residents", "Billing", "Payments", "Maintenance", "Providers", "Reports", "Automation rules", "Payment settings", "Staff"];
const MANAGER_NAV = ["Overview", "Properties and units", "Residents", "Billing", "Maintenance", "Providers", "Staff"];
export default function App() {
  const [me, setMe] = useState(null); const [checked, setChecked] = useState(false);
  useEffect(() => {
    const out = () => setMe(null); window.addEventListener("proplink-signed-out", out);
    if (getToken()) api("/staff/me").then(setMe).catch(() => {}).finally(() => setChecked(true)); else setChecked(true);
    return () => window.removeEventListener("proplink-signed-out", out);
  }, []);
  if (!checked) return <div className="main"><div className="empty">Loading…</div></div>;
  if (!me) return <Login onDone={setMe} />;
  return <Dashboard me={me} signOut={async () => { await api("/staff/logout", "POST").catch(() => {}); setToken(null); setMe(null); }} />;
}

function Dashboard({ me, signOut }) {
  const landlord = me.role === "landlord"; const NAV = landlord ? LANDLORD_NAV : MANAGER_NAV;
  const [page, setPage] = useState("Overview"); const [props, loadProps] = useLoad("/properties"); const [cfg] = useLoad("/config"); const [msg, setMsg] = useState(""); const [tick, setTick] = useState(0);
  const [pidSel, setPidSel] = useState(null); const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  // A toast does not reload the page, so half-filled forms and the activation code stay on screen.
  const toast = (m) => { setMsg(m); setTimeout(() => setMsg(""), 3500); };
  if (!props) return <div className="main"><div className="empty">Connecting to the PropLink API… (is the backend running on port 8000?)</div></div>;
  const prop = props.find((p) => p.id === pidSel) || props[0];
  if (!prop) return <><FirstProperty me={me} onCreated={loadProps} toast={toast} />{msg && <div className="toast">{msg}</div>}</>;
  const pid = prop.id; const P = { pid, toast, me, simulated: cfg?.payments_simulated, reloadProps: loadProps };
  const label = (n) => (n === "Staff" && !landlord ? "My account" : n);
  const body = { Overview: <Overview {...P} />, "Properties and units": <Units {...P} />, Residents: <Residents {...P} />, Billing: <Billing {...P} />, Payments: <Payments {...P} />, Maintenance: <Maintenance {...P} />, Providers: <Providers {...P} />, Reports: <Reports {...P} />, "Automation rules": <Automation {...P} />, "Payment settings": <PaymentSettings {...P} />, Staff: <Staff {...P} /> }[page];
  return (
    <div className="app">
      <nav className="side"><h1>PropLink</h1>{NAV.map((n) => <button key={n} className={n === page ? "on" : ""} onClick={() => setPage(n)}>{label(n)}</button>)}
        <div style={{ marginTop: 24, fontSize: 13, opacity: 0.85 }}>{me.full_name}<br /><small>{me.org} · {me.role}</small></div>
        <button onClick={signOut}>Sign out</button>
        {cfg?.payments_simulated && <div style={{ marginTop: 12, fontSize: 12, opacity: 0.75 }}>Test mode: M-Pesa is simulated</div>}</nav>
      <main className="main">
        <div className="head"><div>
          {props.length > 1 ? <select value={pid} onChange={(e) => setPidSel(+e.target.value)}>{props.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select> : <small>{prop.name}</small>}
          <h2>{label(page)}</h2></div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />
            <button className="btn" onClick={async () => { try { const r = await api("/bills/generate", "POST", { property_id: pid, period }); toast(`${r.created} bills generated for ${r.period}`); setTick((t) => t + 1); } catch (e) { toast(e.message); } }}>Generate bills</button>
          </div></div>
        <div key={`${page}-${pid}-${tick}`}>{body}</div>
      </main>
      {msg && <div className="toast">{msg}</div>}
    </div>
  );
}