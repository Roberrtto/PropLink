import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';

const brand = Color(0xFF12705F);
const ink = Color(0xFF10231E);
const muted = Color(0xFF5D726B);
const bg = Color(0xFFF3F7F6);
const line = Color(0xFFE3EBE8);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.loadToken();
  runApp(const PropLinkApp());
}

String commas(num n) => n.round().toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (m) => ',');
String kes(num n) => 'KES ${commas(n)}';
const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
String day(dynamic s) {
  final d = s is String ? DateTime.tryParse(s) : null;
  return d == null ? '' : '${d.day} ${_months[d.month - 1]}';
}

typedef Json = Map<String, dynamic>;

class PropLinkApp extends StatelessWidget {
  const PropLinkApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'PropLink',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(seedColor: brand),
      scaffoldBackgroundColor: bg,
    ),
    home: ValueListenableBuilder<bool>(
      valueListenable: Api.authed,
      builder: (_, ok,
          _) => ok ? const Shell() : const LoginPage(),
    ),
  );
}

// ---------- shared widgets ----------
class Panel extends StatelessWidget {
  final Widget child;
  const Panel({super.key, required this.child});
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: line)),
    child: child,
  );
}

class Pill extends StatelessWidget {
  final String v;
  const Pill(this.v, {super.key});
  @override
  Widget build(BuildContext context) {
    final m = <String, List<int>>{
      'paid': [0xFFDCF3E8, 0xFF127A4A],
      'pending': [0xFFFDF0CF, 0xFF92620A],
      'overdue': [0xFFFDE0E0, 0xFFB42323],
    }[v] ?? [0xFFE8EEEC, 0xFF10231E];
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(color: Color(m[0]), borderRadius: BorderRadius.circular(99)),
      child: Text(v.isEmpty ? v : v[0].toUpperCase() + v.substring(1),
          style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: Color(m[1]))),
    );
  }
}

class Heading extends StatelessWidget {
  final String text;
  const Heading(this.text, {super.key});
  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.only(top: 16, bottom: 8), child: Text(text, style: const TextStyle(fontWeight: FontWeight.w700, color: ink)));
}

class BillTile extends StatelessWidget {
  final Json b;
  final VoidCallback onTap;
  const BillTile(this.b, {super.key, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final st = b['status'] as String;
    final due = st == 'paid' ? 'Paid' : '${st == 'overdue' ? 'Was due ' : 'Due '}${day(b['due_date'])}';
    return InkWell(
      onTap: st == 'paid' ? null : onTap,
      child: Panel(
        child: Column(children: [
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text('${b['charge_type']} · ${b['period']}', style: const TextStyle(fontWeight: FontWeight.w700)),
            Text(commas(b['amount'] as num), style: const TextStyle(fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 4),
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text(due, style: const TextStyle(fontSize: 12, color: muted)),
            Pill(st),
          ]),
        ]),
      ),
    );
  }
}

class StepRow extends StatelessWidget {
  final int n;
  final String title, sub;
  final bool on;
  const StepRow(this.n, this.title, this.sub, this.on, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      CircleAvatar(radius: 13, backgroundColor: on ? brand : const Color(0xFFE8EEEC), child: Text('$n', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: on ? Colors.white : muted))),
      const SizedBox(width: 12),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
        Text(sub, style: const TextStyle(fontSize: 12, color: muted)),
      ])),
    ]),
  );
}

/// Loads data, shows a spinner or error, and supports pull-to-refresh.
class Fetch extends StatefulWidget {
  final Future<List<dynamic>> Function() load;
  final Widget Function(BuildContext, List<dynamic>, Future<void> Function()) builder;
  const Fetch({super.key, required this.load, required this.builder});
  @override
  State<Fetch> createState() => _FetchState();
}

class _FetchState extends State<Fetch> {
  List<dynamic>? data;
  String? error;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    try {
      final d = await widget.load();
      if (mounted) setState(() { data = d; error = null; });
    } on ApiException catch (e) {
      if (mounted) setState(() => error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (data == null) {
      return Center(
        child: error == null
            ? const CircularProgressIndicator()
            : Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(error!, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: () { setState(() => error = null); refresh(); }, child: const Text('Try again')),
          ]),
        ),
      );
    }
    return RefreshIndicator(onRefresh: refresh, child: widget.builder(context, data!, refresh));
  }
}

Widget scrollList(List<Widget> children) => ListView(
  physics: const AlwaysScrollableScrollPhysics(),
  padding: const EdgeInsets.all(16),
  children: children,
);

// ---------- sign in ----------
class LoginPage extends StatefulWidget {
  const LoginPage({super.key});
  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final phone = TextEditingController();
  final code = TextEditingController();
  bool sent = false, busy = false;
  String? err, dev;

  Future<void> run(Future<void> Function() f) async {
    setState(() { busy = true; err = null; });
    try {
      await f();
    } on ApiException catch (e) {
      err = e.message;
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> send() => run(() async {
    final r = await Api.post('/auth/request-otp', {'phone': phone.text});
    dev = r['dev_code'] as String?;
    sent = true;
  });

  Future<void> verify() => run(() async {
    final r = await Api.post('/auth/verify', {'phone': phone.text, 'code': code.text});
    await Api.saveToken(r['token'] as String);
  });

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('PropLink', style: TextStyle(fontSize: 32, fontWeight: FontWeight.w800, color: ink)),
            const SizedBox(height: 4),
            const Text('Sign in with your phone number', style: TextStyle(color: muted)),
            const SizedBox(height: 24),
            TextField(controller: phone, enabled: !sent, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Phone (07...)', border: OutlineInputBorder(), filled: true, fillColor: Colors.white)),
            if (sent) ...[
              const SizedBox(height: 12),
              TextField(controller: code, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: '6-digit code', border: OutlineInputBorder(), filled: true, fillColor: Colors.white)),
              if (dev != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Demo mode: your code is $dev (no SMS is sent yet)', style: const TextStyle(color: muted))),
            ],
            if (err != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(err!, style: const TextStyle(color: Color(0xFFB42323)))),
            const SizedBox(height: 16),
            FilledButton(onPressed: busy ? null : (sent ? verify : send), child: Padding(padding: const EdgeInsets.all(6), child: Text(sent ? 'Verify and sign in' : 'Send code'))),
          ]),
        ),
      ),
    ),
  );
}

// ---------- shell with bottom navigation ----------
class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int tab = 0, tick = 0;

  Future<void> pay(Json bill, String phone) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => PayPage(bill: bill, phone: phone)));
    if (mounted) setState(() => tick++);
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      HomePage(key: ValueKey('h$tick'), onPay: pay),
      BillsPage(key: ValueKey('b$tick'), onPay: pay),
      ServicesPage(key: ValueKey('s$tick')),
      AccountPage(key: ValueKey('a$tick')),
    ];
    return Scaffold(
      body: SafeArea(child: pages[tab]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() { tab = i; tick++; }),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), label: 'Home'),
          NavigationDestination(icon: Icon(Icons.receipt_long_outlined), label: 'Bills'),
          NavigationDestination(icon: Icon(Icons.build_outlined), label: 'Services'),
          NavigationDestination(icon: Icon(Icons.person_outline), label: 'Account'),
        ],
      ),
    );
  }
}

Future<List<dynamic>> loadMeAndBills() => Future.wait([Api.get('/me'), Api.get('/me/bills')]);

// ---------- home ----------
class HomePage extends StatelessWidget {
  final Future<void> Function(Json, String) onPay;
  const HomePage({super.key, required this.onPay});
  @override
  Widget build(BuildContext context) => Fetch(
    load: loadMeAndBills,
    builder: (c, d, refresh) {
      final me = d[0] as Json;
      final bills = (d[1] as List).cast<Json>();
      final unpaid = bills.where((b) => b['status'] != 'paid').toList()
        ..sort((a, b) => (a['due_date'] as String).compareTo(b['due_date'] as String));
      final next = unpaid.isEmpty ? null : unpaid.first;
      return scrollList([
        Text('${me['property']} · Block ${me['block']}', style: const TextStyle(color: muted)),
        Text('Unit ${me['unit']}', style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: ink)),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(16)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Outstanding balance', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
            Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text(kes(me['balance'] as num), style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w800))),
            Text('${me['unpaid_count']} bills unpaid${me['next_due'] != null ? ' · next due ${day(me['next_due'])}' : ''}', style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Colors.white, foregroundColor: brand),
                onPressed: next == null ? null : () => onPay(next, me['phone'] as String),
                child: const Text('Pay with M-Pesa'),
              ),
            ),
          ]),
        ),
        const Heading('Your bills'),
        if (bills.isEmpty) const Text('No bills yet.', style: TextStyle(color: muted)),
        for (final b in bills.take(6)) BillTile(b, onTap: () => onPay(b, me['phone'] as String)),
      ]);
    },
  );
}

class BillsPage extends StatelessWidget {
  final Future<void> Function(Json, String) onPay;
  const BillsPage({super.key, required this.onPay});
  @override
  Widget build(BuildContext context) => Fetch(
    load: loadMeAndBills,
    builder: (c, d, refresh) {
      final me = d[0] as Json;
      final bills = (d[1] as List).cast<Json>();
      return scrollList([
        const Text('Bills', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: ink)),
        const SizedBox(height: 12),
        if (bills.isEmpty) const Text('No bills yet.', style: TextStyle(color: muted)),
        for (final b in bills) BillTile(b, onTap: () => onPay(b, me['phone'] as String)),
      ]);
    },
  );
}

// ---------- pay ----------
class PayPage extends StatefulWidget {
  final Json bill;
  final String phone;
  const PayPage({super.key, required this.bill, required this.phone});
  @override
  State<PayPage> createState() => _PayPageState();
}

class _PayPageState extends State<PayPage> {
  late final TextEditingController phone = TextEditingController(text: widget.phone);
  Json? req, st;
  String? err;
  Timer? timer;
  bool busy = false;

  bool get done => st != null && (st!['status'] == 'confirmed' || st!['status'] == 'failed');

  @override
  void dispose() {
    timer?.cancel();
    phone.dispose();
    super.dispose();
  }

  Future<void> send() async {
    setState(() { busy = true; err = null; });
    try {
      final r = await Api.post('/me/pay', {'bill_id': widget.bill['id'], 'phone': phone.text});
      setState(() { req = Json.from(r as Map); st = {'status': 'pending'}; });
      timer = Timer.periodic(const Duration(seconds: 2), (_) => poll());
    } on ApiException catch (e) {
      setState(() => err = e.message);
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> poll() async {
    if (req == null) return;
    try {
      final s = await Api.get('/me/payment/${req!['checkout_request_id']}');
      if (!mounted) return;
      setState(() => st = Json.from(s as Map));
      if (done) timer?.cancel();
    } on ApiException catch (_) {}
  }

  Future<void> simulate(String outcome) async {
    try {
      await Api.post('/me/mock/${req!['checkout_request_id']}/$outcome');
      await poll();
    } on ApiException catch (e) {
      if (mounted) setState(() => err = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final b = widget.bill;
    final ok = st?['status'] == 'confirmed';
    return Scaffold(
      appBar: AppBar(title: Text('Pay ${(b['charge_type'] as String).toLowerCase()}'), backgroundColor: bg),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${b['charge_type']} · ${b['period']}', style: const TextStyle(fontSize: 12, color: muted)),
          Text(kes(b['amount'] as num), style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w700)),
        ])),
        const Heading('M-Pesa number'),
        TextField(controller: phone, enabled: req == null, keyboardType: TextInputType.phone, decoration: const InputDecoration(border: OutlineInputBorder(), filled: true, fillColor: Colors.white)),
        if (err != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(err!, style: const TextStyle(color: Color(0xFFB42323)))),
        const SizedBox(height: 12),
        if (req == null) FilledButton(onPressed: busy ? null : send, child: const Padding(padding: EdgeInsets.all(6), child: Text('Send payment request'))),
        if (req != null) ...[
          const Heading('Payment status'),
          Panel(child: Column(children: [
            StepRow(1, 'Request sent', 'Check your phone for the M-Pesa prompt', true),
            StepRow(2, 'Waiting for your PIN', 'Enter your PIN on the prompt', ok),
            StepRow(3, 'Confirmed by M-Pesa', ok ? 'Receipt ${st!['receipt'] ?? ''} · M-Pesa ${st!['mpesa_receipt'] ?? ''}' : 'Receipt issued automatically', ok),
          ])),
          if (st?['status'] == 'failed')
            const Text('Payment was cancelled or failed. The bill is still unpaid.', style: TextStyle(color: Color(0xFFB42323), fontWeight: FontWeight.w700)),
          if (!done)
            Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Text('Demo mode: M-Pesa is simulated. Pretend to answer the phone prompt:', style: TextStyle(color: muted)),
              const SizedBox(height: 8),
              FilledButton(onPressed: () => simulate('success'), child: const Text('Enter PIN (confirm)')),
              const SizedBox(height: 8),
              OutlinedButton(onPressed: () => simulate('fail'), child: const Text('Cancel prompt')),
            ])),
          if (done) FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Done')),
        ],
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: const Color(0xFFE8F1EE), borderRadius: BorderRadius.circular(10)),
          child: const Text('The bill stays Pending until M-Pesa confirms the payment. PropLink never sees or stores your PIN.', style: TextStyle(fontSize: 12, color: muted)),
        ),
      ]),
    );
  }
}

// ---------- services ----------
const stages = ['Submitted', 'Assigned', 'In Progress', 'Completed'];

class ServicesPage extends StatefulWidget {
  const ServicesPage({super.key});
  @override
  State<ServicesPage> createState() => _ServicesPageState();
}

class _ServicesPageState extends State<ServicesPage> {
  String cat = 'Plumbing';
  final title = TextEditingController();
  String? err;

  @override
  void dispose() {
    title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Fetch(
    load: () => Future.wait([Api.get('/me/requests')]),
    builder: (c, d, refresh) {
      final list = (d[0] as List).cast<Json>();
      return scrollList([
        const Text('Services', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: ink)),
        const Heading('Report a problem'),
        Wrap(spacing: 8, children: [
          for (final k in ['Plumbing', 'Electrical', 'Cleaning', 'Other'])
            ChoiceChip(label: Text(k), selected: cat == k, onSelected: (_) => setState(() => cat = k)),
        ]),
        const SizedBox(height: 8),
        TextField(controller: title, decoration: const InputDecoration(hintText: 'What is wrong? e.g. Leaking kitchen tap', border: OutlineInputBorder(), filled: true, fillColor: Colors.white)),
        if (err != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(err!, style: const TextStyle(color: Color(0xFFB42323)))),
        const SizedBox(height: 8),
        FilledButton(
          onPressed: () async {
            if (title.text.trim().isEmpty) return;
            try {
              await Api.post('/me/requests', {'category': cat, 'title': title.text.trim()});
              title.clear();
              setState(() => err = null);
              await refresh();
            } on ApiException catch (e) {
              setState(() => err = e.message);
            }
          },
          child: const Text('Submit request'),
        ),
        const Heading('Your requests'),
        if (list.isEmpty) const Text('No requests yet.', style: TextStyle(color: muted)),
        for (final r in list)
          InkWell(
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => RequestPage(r: r))),
            child: Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                Expanded(child: Text('${r['title']}', style: const TextStyle(fontWeight: FontWeight.w700))),
                Text('${r['status']}', style: const TextStyle(color: brand, fontWeight: FontWeight.w700)),
              ]),
              Text('${r['category']} · ${day(r['created_at'])}', style: const TextStyle(fontSize: 12, color: muted)),
            ])),
          ),
      ]);
    },
  );
}

class RequestPage extends StatelessWidget {
  final Json r;
  const RequestPage({super.key, required this.r});
  @override
  Widget build(BuildContext context) {
    final idx = stages.indexOf(r['status'] as String);
    final cost = (r['cost'] as num?) ?? 0;
    final desc = [
      day(r['created_at']),
      r['provider'] != null ? '${day(r['updated_at'])} · ${r['provider']}' : 'Waiting for assignment',
      'Provider is on the job',
      cost > 0 ? 'Work completed · cost ${kes(cost)}' : 'Work record and cost added here',
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Service request'), backgroundColor: bg),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Chip(label: Text('${r['category']}')),
          Text('${r['title']}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
          Text('Reported ${day(r['created_at'])}', style: const TextStyle(fontSize: 12, color: muted)),
        ])),
        const Heading('Progress'),
        Panel(child: Column(children: [for (var i = 0; i < stages.length; i++) StepRow(i + 1, stages[i], desc[i], i <= idx)])),
      ]),
    );
  }
}

// ---------- account ----------
class AccountPage extends StatelessWidget {
  const AccountPage({super.key});
  @override
  Widget build(BuildContext context) => Fetch(
    load: () => Future.wait([Api.get('/me'), Api.get('/me/receipts'), Api.get('/me/notifications')]),
    builder: (c, d, refresh) {
      final me = d[0] as Json;
      final receipts = (d[1] as List).cast<Json>();
      final notes = (d[2] as List).cast<Json>();
      return scrollList([
        const Text('Account', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: ink)),
        const SizedBox(height: 12),
        Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${me['name']}', style: const TextStyle(fontWeight: FontWeight.w700)),
          Text('${me['phone']} · Unit ${me['unit']}, Block ${me['block']}', style: const TextStyle(color: muted)),
          Text('${me['property']}', style: const TextStyle(color: muted)),
        ])),
        const Heading('Receipts'),
        if (receipts.isEmpty) const Text('No receipts yet.', style: TextStyle(color: muted)),
        for (final r in receipts)
          Panel(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              Text('${r['charge']} · ${r['period']}', style: const TextStyle(fontWeight: FontWeight.w700)),
              Text(commas(r['amount'] as num), style: const TextStyle(fontWeight: FontWeight.w700)),
            ]),
            Text('${r['number']} · ${day(r['issued_at'])}', style: const TextStyle(fontSize: 12, color: muted)),
          ])),
        const Heading('Notifications'),
        if (notes.isEmpty) const Text('Nothing new.', style: TextStyle(color: muted)),
        for (final n in notes) Panel(child: Text('${n['message']}')),
        const SizedBox(height: 12),
        OutlinedButton(onPressed: () => Api.saveToken(null), child: const Text('Sign out')),
      ]);
    },
  );
}