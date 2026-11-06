import React, { useState, useEffect, useCallback } from 'react';
import { SafeAreaView, View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, StatusBar, RefreshControl, Platform } from 'react-native';

// Android emulator reaches your PC at 10.0.2.2. On a real phone either run `adb reverse tcp:8000 tcp:8000`
// and use http://localhost:8000, or put your PC's Wi-Fi address here (e.g. http://192.168.1.20:8000).
const BASE = Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
let TOKEN = null;
const api = async (path, method = 'GET', body) => {
  const r = await fetch(BASE + '/api' + path, { method, headers: { 'Content-Type': 'application/json', ...(TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {}) }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Request failed');
  return j;
};
const kes = (n) => 'KES ' + Number(n || 0).toLocaleString();
const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const day = (s) => { if (!s) return ''; const d = new Date(s); return d.getDate() + ' ' + M[d.getMonth()]; };
const C = { ink: '#10231e', muted: '#5d726b', brand: '#12705f', bg: '#f3f7f6', line: '#e3ebe8' };
const PILL = { paid: ['#dcf3e8', '#127a4a'], pending: ['#fdf0cf', '#92620a'], overdue: ['#fde0e0', '#b42323'] };

function useLoad(path) {
  const [data, setData] = useState(null); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setBusy(true); try { setData(await api(path)); } catch (e) { setData(null); } setBusy(false); }, [path]);
  useEffect(() => { load(); }, [load]);
  return [data, load, busy];
}
const Btn = ({ title, onPress, style, ghost, disabled }) => (
  <TouchableOpacity disabled={disabled} onPress={onPress} style={[s.btn, ghost && s.ghost, disabled && { opacity: 0.5 }, style]}><Text style={[s.btnT, ghost && { color: C.brand }]}>{title}</Text></TouchableOpacity>);
const Pill = ({ v }) => { const [bg, fg] = PILL[v] || ['#e8eeec', C.ink]; return <Text style={[s.pill, { backgroundColor: bg, color: fg }]}>{v[0].toUpperCase() + v.slice(1)}</Text>; };
const Err = ({ e }) => (e ? <Text style={{ color: '#b42323', marginVertical: 6 }}>{e}</Text> : null);
const Page = ({ title, back, onRefresh, busy, children }) => (
  <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 16 }} refreshControl={onRefresh && <RefreshControl refreshing={!!busy} onRefresh={onRefresh} />}>
    {back && <TouchableOpacity onPress={back}><Text style={{ color: C.brand, fontWeight: '700', marginBottom: 8 }}>← Back</Text></TouchableOpacity>}
    {title && <Text style={s.h1}>{title}</Text>}{children}</ScrollView>);

function Login({ onDone }) {
  const [phone, setPhone] = useState(''); const [code, setCode] = useState(''); const [sent, setSent] = useState(false); const [dev, setDev] = useState(null); const [err, setErr] = useState('');
  const send = async () => { try { setErr(''); const r = await api('/auth/request-otp', 'POST', { phone }); setDev(r.dev_code); setSent(true); } catch (e) { setErr(e.message); } };
  const verify = async () => { try { setErr(''); const r = await api('/auth/verify', 'POST', { phone, code }); TOKEN = r.token; onDone(); } catch (e) { setErr(e.message); } };
  return (
    <View style={{ flex: 1, justifyContent: 'center', padding: 24 }}>
      <Text style={[s.h1, { fontSize: 32 }]}>PropLink</Text><Text style={{ color: C.muted, marginBottom: 24 }}>Sign in with your phone number</Text>
      <TextInput style={s.input} placeholder="Phone (07…)" keyboardType="phone-pad" value={phone} onChangeText={setPhone} editable={!sent} />
      {sent && <>
        <TextInput style={s.input} placeholder="6-digit code" keyboardType="number-pad" value={code} onChangeText={setCode} />
        {dev && <Text style={{ color: C.muted, marginBottom: 8 }}>Demo mode: your code is {dev} (no SMS is sent yet)</Text>}</>}
      <Err e={err} />
      <Btn title={sent ? 'Verify and sign in' : 'Send code'} onPress={sent ? verify : send} />
    </View>);
}

function BillRow({ b, onPay }) {
  const due = b.status === 'paid' ? 'Paid' : (b.status === 'overdue' ? 'Was due ' : 'Due ') + day(b.due_date);
  return (
    <TouchableOpacity disabled={b.status === 'paid'} onPress={() => onPay(b)} style={s.card}>
      <View style={s.rowBetween}><Text style={s.bold}>{b.charge_type} · {b.period}</Text><Text style={s.bold}>{b.amount.toLocaleString()}</Text></View>
      <View style={s.rowBetween}><Text style={{ color: C.muted, fontSize: 12 }}>{due}</Text><Pill v={b.status} /></View>
    </TouchableOpacity>);
}

function Home({ onPay, tick }) {
  const [me, reload, busy] = useLoad('/me'); const [bills, reloadB] = useLoad('/me/bills');
  useEffect(() => { reload(); reloadB(); }, [tick]);
  if (!me) return <Page><Text style={{ color: C.muted }}>Loading…</Text></Page>;
  const next = (bills || []).filter((b) => b.status !== 'paid').sort((a, b) => a.due_date.localeCompare(b.due_date))[0];
  return (
    <Page onRefresh={() => { reload(); reloadB(); }} busy={busy}>
      <Text style={{ color: C.muted }}>{me.property} · Block {me.block}</Text><Text style={s.h1}>Unit {me.unit}</Text>
      <View style={s.hero}>
        <Text style={{ color: '#fff', fontWeight: '600' }}>Outstanding balance</Text>
        <Text style={s.heroAmt}>{kes(me.balance)}</Text>
        <Text style={{ color: '#d6efe8', marginBottom: 12 }}>{me.unpaid_count} bills unpaid{me.next_due ? ' · next due ' + day(me.next_due) : ''}</Text>
        <TouchableOpacity disabled={!next} onPress={() => onPay(next)} style={[s.heroBtn, !next && { opacity: 0.5 }]}><Text style={{ color: C.brand, fontWeight: '700' }}>Pay with M-Pesa</Text></TouchableOpacity>
      </View>
      <Text style={s.sec}>Your bills</Text>
      {(bills || []).slice(0, 6).map((b) => <BillRow key={b.id} b={b} onPay={onPay} />)}
    </Page>);
}

function Bills({ onPay, tick }) {
  const [bills, load, busy] = useLoad('/me/bills'); useEffect(() => { load(); }, [tick]);
  return <Page title="Bills" onRefresh={load} busy={busy}>{(bills || []).length ? bills.map((b) => <BillRow key={b.id} b={b} onPay={onPay} />) : <Text style={{ color: C.muted }}>No bills yet.</Text>}</Page>;
}

function Pay({ bill, phone0, onClose }) {
  const [phone, setPhone] = useState(phone0 || ''); const [req, setReq] = useState(null); const [st, setSt] = useState(null); const [err, setErr] = useState('');
  const done = st && (st.status === 'confirmed' || st.status === 'failed');
  useEffect(() => {
    if (!req || done) return;
    const id = setInterval(() => api('/me/payment/' + req.checkout_request_id).then(setSt).catch(() => {}), 2000);
    return () => clearInterval(id);
  }, [req, done]);
  const send = async () => { try { setErr(''); setReq(await api('/me/pay', 'POST', { bill_id: bill.id, phone })); setSt({ status: 'pending' }); } catch (e) { setErr(e.message); } };
  const sim = (o) => api(`/me/mock/${req.checkout_request_id}/${o}`, 'POST').then(() => api('/me/payment/' + req.checkout_request_id).then(setSt)).catch((e) => setErr(e.message));
  const ok = st && st.status === 'confirmed';
  const steps = [['Request sent', 'Check your phone for the M-Pesa prompt', !!req], ['Waiting for your PIN', 'Enter your PIN on the prompt', ok], ['Confirmed by M-Pesa', ok ? 'Receipt ' + (st.receipt || '') + ' · M-Pesa ' + (st.mpesa_receipt || '') : 'Receipt issued automatically', ok]];
  return (
    <Page title={'Pay ' + bill.charge_type.toLowerCase()} back={onClose}>
      <View style={s.card}><Text style={{ color: C.muted, fontSize: 12 }}>{bill.charge_type} · {bill.period}</Text><Text style={{ fontSize: 30, fontWeight: '700' }}>{kes(bill.amount)}</Text></View>
      <Text style={s.sec}>M-Pesa number</Text>
      <TextInput style={s.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" editable={!req} />
      <Err e={err} />
      {!req && <Btn title="Send payment request" onPress={send} />}
      {req && <>
        <Text style={s.sec}>Payment status</Text>
        <View style={s.card}>{steps.map(([t, d, on], i) => (
          <View key={t} style={{ flexDirection: 'row', marginVertical: 6 }}>
            <Text style={[s.dot, on && { backgroundColor: C.brand, color: '#fff' }]}>{i + 1}</Text>
            <View style={{ flex: 1 }}><Text style={s.bold}>{t}</Text><Text style={{ color: C.muted, fontSize: 12 }}>{d}</Text></View></View>))}</View>
        {st && st.status === 'failed' && <Text style={{ color: '#b42323', fontWeight: '700' }}>Payment was cancelled or failed. The bill is still unpaid.</Text>}
        {!done && <View style={s.card}><Text style={{ color: C.muted, marginBottom: 8 }}>Demo mode: M-Pesa is simulated. Pretend to answer the phone prompt:</Text>
          <Btn title="Enter PIN (confirm)" onPress={() => sim('success')} /><Btn ghost style={{ marginTop: 8 }} title="Cancel prompt" onPress={() => sim('fail')} /></View>}
        {done && <Btn title="Done" onPress={onClose} />}</>}
      <Text style={s.note}>The bill stays Pending until M-Pesa confirms the payment. PropLink never sees or stores your PIN.</Text>
    </Page>);
}

const STAGES = ['Submitted', 'Assigned', 'In Progress', 'Completed'];
function Services({ tick }) {
  const [list, load, busy] = useLoad('/me/requests'); const [open, setOpen] = useState(null); const [cat, setCat] = useState('Plumbing'); const [title, setTitle] = useState(''); const [err, setErr] = useState('');
  useEffect(() => { load(); }, [tick]);
  const add = async () => { try { setErr(''); await api('/me/requests', 'POST', { category: cat, title }); setTitle(''); load(); } catch (e) { setErr(e.message); } };
  const sel = (list || []).find((r) => r.id === open);
  if (sel) {
    const idx = STAGES.indexOf(sel.status);
    const desc = [day(sel.created_at), sel.provider ? day(sel.updated_at) + ' · ' + sel.provider : 'Waiting for assignment', 'Provider is on the job', sel.cost ? 'Work completed · cost ' + kes(sel.cost) : 'Work record and cost added here'];
    return (
      <Page title="Service request" back={() => setOpen(null)}>
        <View style={s.card}><Text style={s.tag}>{sel.category}</Text><Text style={{ fontSize: 20, fontWeight: '700' }}>{sel.title}</Text><Text style={{ color: C.muted, fontSize: 12 }}>Reported {day(sel.created_at)}</Text></View>
        <Text style={s.sec}>Progress</Text>
        <View style={s.card}>{STAGES.map((t, i) => (<View key={t} style={{ flexDirection: 'row', marginVertical: 6 }}>
          <Text style={[s.dot, i <= idx && { backgroundColor: C.brand, color: '#fff' }]}>{i + 1}</Text>
          <View><Text style={s.bold}>{t}</Text><Text style={{ color: C.muted, fontSize: 12 }}>{desc[i]}</Text></View></View>))}</View>
      </Page>);
  }
  return (
    <Page title="Services" onRefresh={load} busy={busy}>
      <Text style={s.sec}>Report a problem</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 8 }}>{['Plumbing', 'Electrical', 'Cleaning', 'Other'].map((c) => (
        <TouchableOpacity key={c} onPress={() => setCat(c)} style={[s.chip, cat === c && { backgroundColor: C.brand }]}><Text style={{ color: cat === c ? '#fff' : C.brand }}>{c}</Text></TouchableOpacity>))}</View>
      <TextInput style={s.input} placeholder="What is wrong? e.g. Leaking kitchen tap" value={title} onChangeText={setTitle} />
      <Err e={err} /><Btn title="Submit request" onPress={add} disabled={!title.trim()} />
      <Text style={s.sec}>Your requests</Text>
      {(list || []).length ? list.map((r) => (
        <TouchableOpacity key={r.id} style={s.card} onPress={() => setOpen(r.id)}><View style={s.rowBetween}><Text style={s.bold}>{r.title}</Text><Text style={{ color: C.brand, fontWeight: '700' }}>{r.status}</Text></View>
          <Text style={{ color: C.muted, fontSize: 12 }}>{r.category} · {day(r.created_at)}</Text></TouchableOpacity>)) : <Text style={{ color: C.muted }}>No requests yet.</Text>}
    </Page>);
}

function Account({ onLogout, tick }) {
  const [me] = useLoad('/me'); const [rc, load, busy] = useLoad('/me/receipts'); const [nt, loadN] = useLoad('/me/notifications');
  useEffect(() => { load(); loadN(); }, [tick]);
  return (
    <Page title="Account" onRefresh={() => { load(); loadN(); }} busy={busy}>
      {me && <View style={s.card}><Text style={s.bold}>{me.name}</Text><Text style={{ color: C.muted }}>{me.phone} · Unit {me.unit}, Block {me.block}</Text><Text style={{ color: C.muted }}>{me.property}</Text></View>}
      <Text style={s.sec}>Receipts</Text>
      {(rc || []).length ? rc.map((r) => <View key={r.number} style={s.card}><View style={s.rowBetween}><Text style={s.bold}>{r.charge} · {r.period}</Text><Text style={s.bold}>{r.amount.toLocaleString()}</Text></View><Text style={{ color: C.muted, fontSize: 12 }}>{r.number} · {day(r.issued_at)}</Text></View>) : <Text style={{ color: C.muted }}>No receipts yet.</Text>}
      <Text style={s.sec}>Notifications</Text>
      {(nt || []).length ? nt.map((n) => <View key={n.id} style={s.card}><Text>{n.message}</Text></View>) : <Text style={{ color: C.muted }}>Nothing new.</Text>}
      <Btn ghost style={{ marginTop: 16 }} title="Sign out" onPress={onLogout} />
    </Page>);
}

export default function App() {
  const [authed, setAuthed] = useState(false); const [tab, setTab] = useState('Home'); const [bill, setBill] = useState(null); const [phone, setPhone] = useState('');
  const [tick, setTick] = useState(0);
  const startPay = async (b) => { try { setPhone((await api('/me')).phone); } catch (e) {} setBill(b); };
  const close = () => { setBill(null); setTick((t) => t + 1); };
  let body;
  if (!authed) body = <Login onDone={() => setAuthed(true)} />;
  else if (bill) body = <Pay bill={bill} phone0={phone} onClose={close} />;
  else body = { Home: <Home onPay={startPay} tick={tick} />, Bills: <Bills onPay={startPay} tick={tick} />, Services: <Services tick={tick} />, Account: <Account tick={tick} onLogout={() => { TOKEN = null; setAuthed(false); setTab('Home'); }} /> }[tab];
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }}>
      <StatusBar barStyle="dark-content" backgroundColor={C.bg} />
      <View style={{ flex: 1 }}>{body}</View>
      {authed && !bill && <View style={s.tabs}>{['Home', 'Bills', 'Services', 'Account'].map((t) => (
        <TouchableOpacity key={t} style={{ flex: 1, alignItems: 'center', padding: 14 }} onPress={() => setTab(t)}><Text style={{ color: tab === t ? C.brand : C.muted, fontWeight: tab === t ? '700' : '400' }}>{t}</Text></TouchableOpacity>))}</View>}
    </SafeAreaView>);
}

const s = StyleSheet.create({
  h1: { fontSize: 26, fontWeight: '700', color: C.ink, marginBottom: 12 }, sec: { fontWeight: '700', color: C.ink, marginTop: 16, marginBottom: 8 },
  card: { backgroundColor: '#fff', borderRadius: 12, borderWidth: 1, borderColor: C.line, padding: 14, marginBottom: 10 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginVertical: 2 }, bold: { fontWeight: '700', color: C.ink },
  pill: { fontSize: 11, fontWeight: '700', paddingHorizontal: 9, paddingVertical: 2, borderRadius: 99, overflow: 'hidden' },
  hero: { backgroundColor: C.brand, borderRadius: 16, padding: 18 }, heroAmt: { color: '#fff', fontSize: 34, fontWeight: '800', marginVertical: 4 },
  heroBtn: { backgroundColor: '#fff', borderRadius: 10, padding: 12, alignItems: 'center' },
  btn: { backgroundColor: C.brand, borderRadius: 10, padding: 14, alignItems: 'center' }, ghost: { backgroundColor: '#e8f1ee' }, btnT: { color: '#fff', fontWeight: '700' },
  input: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#cfdcd7', borderRadius: 10, padding: 12, fontSize: 16, marginBottom: 10, color: C.ink },
  dot: { width: 26, height: 26, borderRadius: 13, backgroundColor: '#e8eeec', textAlign: 'center', textAlignVertical: 'center', marginRight: 12, fontWeight: '700', color: C.muted, overflow: 'hidden' },
  note: { backgroundColor: '#e8f1ee', color: C.muted, padding: 12, borderRadius: 10, marginTop: 12, fontSize: 12 },
  tag: { alignSelf: 'flex-start', backgroundColor: '#e3ecfb', color: '#1f5aa8', fontSize: 11, fontWeight: '700', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 99, overflow: 'hidden', marginBottom: 4 },
  chip: { borderWidth: 1, borderColor: C.brand, borderRadius: 99, paddingHorizontal: 14, paddingVertical: 6, marginRight: 8, marginBottom: 8 },
  tabs: { flexDirection: 'row', backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: C.line },
});
