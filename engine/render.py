"""HTML rendering for the live dashboard (index.html) and the weekly self-contained archive
(reports/<season>/weekNN.html). Same renderer, same data, no external fetches: every number is
inlined in the file, so the page works with no network and never quietly goes stale. The only
script on the page computes the data age from the build timestamp and turns the banner red."""
import html
import json
import re

from . import config
from .timeutil import parse_iso, to_central

STATUS_ICON = {"ok": "OK", "warn": "CHECK", "info": "NOTE", "fail": "FAIL"}


def esc(v):
    return html.escape("" if v is None else str(v))


def num(v, d=1):
    if v is None:
        return "-"
    if isinstance(v, (int, float)):
        return f"{v:.{d}f}" if isinstance(v, float) or d else str(v)
    return esc(v)


def central(iso_s, fmt="%a %b %d, %I:%M %p"):
    t = parse_iso(iso_s)
    if not t:
        return "-"
    c = to_central(t)
    return c.strftime(fmt).replace(" 0", " ") + f" {c.tzname()}"


def md_to_html(md):
    """Tiny markdown subset: #/##/### headings, - bullets, **bold**, blank-line paragraphs, links."""
    out, in_list = [], False
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = len(m.group(1)) + 2
            out.append(f"<h{lvl}>{m.group(2)}</h{lvl}>")
        elif s.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{s.lstrip()[2:]}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{s}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--muted:#5c6774;--line:#e1e5ea;--ok:#1a7f4b;--warn:#b7791f;--bad:#c0392b;--info:#2f6fb7;--mine:#fff8e1;--head:#eef2f6;
--okbg:#e7f4ec;--warnbg:#fff4e0;--badbg:#fdecea;--infobg:#e8f0fb;--synth:#7b4fb5;--tabbg:#fff;--tabon:#1c2430;--tabonink:#fff}
@media (prefers-color-scheme: dark){:root{--bg:#0f1419;--card:#181e26;--ink:#e6e9ee;--muted:#9aa5b1;--line:#2b3440;--ok:#4cc38a;--warn:#e0a94a;--bad:#f0706a;--info:#6fa8ef;--mine:#2a2611;--head:#222a34;
--okbg:#163524;--warnbg:#3a2e14;--badbg:#3c1f1d;--infobg:#1c2b40;--synth:#a884dc;--tabbg:#181e26;--tabon:#e6e9ee;--tabonink:#0f1419}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}body{margin:0;font:14px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg);overflow-x:hidden}
a{color:var(--info)}h1{font-size:22px;margin:0}h2{font-size:18px;margin:0 0 8px;border-bottom:2px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:14px 0 6px}h4{font-size:14px;margin:10px 0 4px}h5{font-size:13px;margin:8px 0 4px}
.wrap{max-width:1380px;margin:0 auto;padding:12px 16px 40px}
.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:10px}
.age{font-size:15px;padding:6px 12px;border-radius:6px;background:var(--okbg);color:var(--ok);font-weight:600}
.age.stale{background:var(--badbg);color:var(--bad)}.age.aging{background:var(--warnbg);color:var(--warn)}
.banner{display:none;background:var(--bad);color:#fff;padding:10px 14px;border-radius:6px;margin:8px 0;font-weight:600}
.banner.show{display:block}.banner.warnb{background:var(--warn)}
.jobs{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 12px}.job{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font-size:12.5px}
.job b{display:block}.job.ok b{color:var(--ok)}.job.fail b{color:var(--bad)}.job.none b{color:var(--muted)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.grid.one{grid-template-columns:1fr}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:14px}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;margin:4px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th{background:var(--head);text-align:left;padding:5px 7px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:5px 7px;border-bottom:1px solid var(--line);vertical-align:top}tr.mine td{background:var(--mine)}tr.start td{font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.why{color:var(--muted);font-size:12.5px}
.tag{display:inline-block;padding:1px 6px;border-radius:4px;font-size:11.5px;font-weight:600;margin-right:4px}
.tag.Q,.tag.Questionable{background:var(--warnbg);color:var(--warn)}.tag.D,.tag.Doubtful{background:var(--badbg);color:var(--bad)}.tag.Out,.tag.IR,.tag.PUP,.tag.Sus{background:var(--badbg);color:var(--bad)}
.tag.ok{background:var(--okbg);color:var(--ok)}.tag.warn{background:var(--warnbg);color:var(--warn)}.tag.fail{background:var(--badbg);color:var(--bad)}.tag.info{background:var(--infobg);color:var(--info)}
.tag.high{background:var(--badbg);color:var(--bad)}.tag.medium{background:var(--warnbg);color:var(--warn)}.tag.low{background:var(--infobg);color:var(--info)}
.machine{border-left:5px solid var(--info)}.synth{border-left:5px solid var(--synth)}.label{font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700}
.muted{color:var(--muted)}.small{font-size:12.5px}ul.tight{margin:6px 0;padding-left:20px}ul.tight li{margin:3px 0}
.pos{font-weight:600;color:var(--muted)}.bid{font-size:16px;font-weight:700;color:var(--ok)}.neg{color:var(--bad)}.posv{color:var(--ok)}
details summary{cursor:pointer;color:var(--info);font-size:13px;padding:6px 0;min-height:32px}
.kpi{display:flex;gap:10px;flex-wrap:wrap;margin:6px 0 10px}.kpi div{background:var(--head);border-radius:6px;padding:6px 12px}.kpi b{font-size:18px;display:block}
code{background:var(--head);padding:1px 4px;border-radius:3px;font-size:12.5px}
/* tabs: every panel is in the HTML; JS only toggles the tabs-on class. Without JS everything shows. */
.tabbar{display:flex;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;padding:4px 0 8px;margin:0 0 6px;position:sticky;top:0;background:var(--bg);z-index:5;scrollbar-width:none}
.tabbar::-webkit-scrollbar{display:none}
.tab{flex:0 0 auto;min-height:44px;padding:10px 14px;border:1px solid var(--line);border-radius:8px;background:var(--tabbg);color:var(--ink);font:inherit;font-weight:600;font-size:14px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;white-space:nowrap}
.tab.on{background:var(--tabon);color:var(--tabonink);border-color:var(--tabon)}
.tab.all{margin-left:auto;font-weight:500;color:var(--muted)}
.tabs-on .panel{display:none}.tabs-on .panel.on{display:block}
.foot{font-size:12.5px;color:var(--muted);margin-top:10px}.foot a{margin-right:10px}
@media (max-width:760px){.grid{grid-template-columns:1fr}.wrap{padding:10px 12px 40px}h1{font-size:19px}.kpi b{font-size:16px}.card{padding:12px 12px}th,td{padding:6px 6px}}
@media print{.tabs-on .panel{display:block!important}.tabbar{display:none}.age{display:none}}
"""

JS = """
(function(){
  var built = new Date(document.body.getAttribute('data-built'));
  var stale = parseFloat(document.body.getAttribute('data-stale-hours'));
  var isArchive = document.body.getAttribute('data-archive') === '1';
  function fmt(h){ if (h < 1) return Math.round(h*60) + ' minutes'; if (h < 48) return h.toFixed(1) + ' hours'; return (h/24).toFixed(1) + ' days'; }
  function tick(){
    var h = (Date.now() - built.getTime()) / 36e5;
    var el = document.getElementById('age');
    el.textContent = (isArchive ? 'Archive built ' : 'Data age: ') + fmt(h) + ' ago';
    var b = document.getElementById('stale-banner');
    el.classList.remove('stale','aging');
    if (!isArchive && h > stale) { el.classList.add('stale'); b.classList.add('show');
      b.textContent = 'STALE: the last successful build was ' + fmt(h) + ' ago. A scheduled run has failed or not fired. Check the Actions tab on GitHub before trusting anything below.'; }
    else if (!isArchive && h > stale * 0.6) { el.classList.add('aging'); }
  }
  tick(); setInterval(tick, 60000);

  // Tabs. Every panel is already in the page; this only hides the ones not selected.
  var body = document.body;
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tabbar .tab[data-tab]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('.panel'));
  var allBtn = document.getElementById('tab-all');
  if (!tabs.length || !panels.length) return;
  var showAll = false;
  try { showAll = localStorage.getItem('psl-show-all') === '1'; } catch (e) {}
  function panelFor(hash){
    var id = (hash || '').replace('#', '');
    if (!id) return null;
    var el = document.getElementById(id);
    while (el && el !== body) { if (el.classList && el.classList.contains('panel')) return el; el = el.parentNode; }
    return null;
  }
  function defaultPanel(){
    // Wednesday is waiver day (bids are due before the Thursday 2 AM run); every other day the lineup matters most.
    var day = new Date().getDay();
    return document.getElementById(day === 3 ? 'tab-waivers' : 'tab-lineup') || panels[0];
  }
  function apply(hash, fromClick){
    var target = panelFor(hash) || defaultPanel();
    body.classList.toggle('tabs-on', !showAll);
    panels.forEach(function(p){ p.classList.toggle('on', p === target); });
    tabs.forEach(function(t){ var on = t.getAttribute('data-tab') === target.id; t.classList.toggle('on', on); t.setAttribute('aria-selected', on ? 'true' : 'false'); });
    if (allBtn) { allBtn.textContent = showAll ? 'Back to tabs' : 'Show everything'; allBtn.setAttribute('aria-pressed', showAll ? 'true' : 'false'); }
    var id = (hash || '').replace('#', '');
    var inner = id && id !== target.id ? document.getElementById(id) : null;
    if (inner) { try { inner.scrollIntoView(); } catch (e) {} }
    else if (fromClick) { window.scrollTo(0, 0); }
  }
  tabs.forEach(function(t){
    t.addEventListener('click', function(ev){
      ev.preventDefault();
      var id = t.getAttribute('data-tab');
      if (('#' + id) !== location.hash) { try { history.replaceState(null, '', '#' + id); } catch (e) { location.hash = id; } }
      apply('#' + id, true);
    });
  });
  if (allBtn) {
    allBtn.addEventListener('click', function(){
      showAll = !showAll;
      try { localStorage.setItem('psl-show-all', showAll ? '1' : '0'); } catch (e) {}
      apply(location.hash, false);
    });
  }
  window.addEventListener('hashchange', function(){ apply(location.hash, false); });
  apply(location.hash, false);
})();
"""


def inj_tag(status):
    return f'<span class="tag {esc(status)}">{esc(status)}</span>' if status else ""


def _vac_cell(r):
    """The vacated-share cell. Display only: it is never part of Expected."""
    sig = r.get("vacated")
    if not sig:
        return "<td class='n muted'>-</td>"
    if not sig.get("n_out"):
        return "<td class='n muted' title='No teammate at his position is ruled out.'>0.0</td>"
    who = ", ".join(d["name"] for d in sig["out"][:3]) + ("..." if sig["n_out"] > 3 else "")
    pct = []
    if sig.get("absorbed_tgt"):
        pct.append(f"{sig['absorbed_tgt'] * 100:.0f}% tgt")
    if sig.get("absorbed_car"):
        pct.append(f"{sig['absorbed_car'] * 100:.0f}% car")
    return (f"<td class=n title=\"{esc(sig.get('why'))}\"><b>{num(sig.get('points'))}</b>"
            f"<div class='small muted'>{esc(' / '.join(pct))}{' from ' + esc(who) if pct else esc(who)}</div></td>")


def lineup_table(rows, show_slot=True, started_cols=False):
    h = ["<table><tr>" + ("<th>Slot</th>" if show_slot else "") +
         "<th>Player</th><th>Pos</th><th>Tm</th><th>Opp</th><th class=n>Sleeper</th><th class=n>Preseason</th><th class=n>Season avg</th>"
         "<th class=n>Expected</th><th class=n>Vacated share</th><th>Injury</th><th>Why</th></tr>"]
    for r in rows:
        if not r.get("player_id"):
            h.append(f"<tr><td>{esc(r.get('slot'))}</td><td colspan=11 class=muted>EMPTY slot</td></tr>")
            continue
        avg = f"{num(r.get('season_avg'))} ({r.get('n_games')})" if r.get("season_avg") is not None else "-"
        extra = ""
        if r.get("started"):
            extra = f" <span class='tag info'>kicked off, {num(r.get('actual_so_far'))} so far</span>"
        h.append(f"<tr class='{'start' if r.get('slot') not in ('BN', 'IR') else ''}'>"
                 + (f"<td>{esc(r.get('slot'))}</td>" if show_slot else "")
                 + f"<td>{esc(r.get('name'))}{extra}</td><td class=pos>{esc(r.get('pos'))}</td><td>{esc(r.get('team'))}</td>"
                 f"<td>{'BYE' if r.get('bye') else esc(r.get('opp') or '-')}</td><td class=n>{num(r.get('sleeper'))}</td>"
                 f"<td class=n>{num(r.get('preseason'))}</td><td class=n>{avg}</td><td class=n><b>{num(r.get('expected'))}</b></td>"
                 + _vac_cell(r) +
                 f"<td>{inj_tag(r.get('injury_status'))}</td><td class=why>{esc(r.get('why'))}</td></tr>")
    h.append("</table>")
    return "".join(h)


def section_lineup(rec, ctx_completed_block):
    L = [f"<div class=card id=lineup><h2>Week {rec['week']}: start/sit</h2>"]
    L.append("<div class=kpi>" + f"<div><b>{num(rec['expected_total'])}</b>expected points, recommended lineup</div>"
             + f"<div><b>{len(rec['changes'])}</b>change{'s' if len(rec['changes']) != 1 else ''} vs your current Sleeper lineup</div>"
             + f"<div><b>{esc(rec['source'].get('kind'))}</b>projection source, {central(rec['source'].get('taken_at_utc'))}</div></div>")
    if rec["changes"]:
        L.append("<h3>Changes to make</h3><ul class=tight>")
        for c in rec["changes"]:
            L.append(f"<li><b>Start {esc(c['in'])}, sit {esc(c['out'])}.</b> <span class=why>{esc(c['why'])}</span></li>")
        L.append("</ul>")
    else:
        L.append("<p class=posv><b>Your current Sleeper lineup already matches the recommendation.</b></p>")
    L.append("<h3>Recommended lineup</h3>" + lineup_table(rec["lineup"]))
    if rec["close_calls"]:
        L.append("<h3>Close calls</h3><ul class=tight>")
        for c in rec["close_calls"]:
            vac = ""
            if c.get("vacated_note"):
                vac = (f" <span class='why muted'>{esc(c['vacated_note'])}</span>")
            L.append(f"<li>{esc(c['slot'])}: <b>{esc(c['starter'])}</b> over {esc(c['bench'])}. "
                     f"<span class=why>{esc(c['why'])}</span>{vac}</li>")
        L.append("</ul>")
    L.append("<details><summary>Bench and IR</summary>" + lineup_table(rec["bench"] + rec["ir"]) + "</details>")
    for n in rec["notes"]:
        L.append(f"<p class='small muted'>{esc(n)}</p>")
    vm = rec.get("vacated_meta") or {}
    if vm.get("available"):
        L.append(f"<p class='small muted'>Vacated share: {esc(vm.get('note'))} Usage through week "
                 f"{max(vm.get('weeks_of_usage') or [0])} of the nflverse weekly file, written {central(vm.get('pulled_at_utc'))}; "
                 f"{vm.get('n_players', 0)} of your skill players matched"
                 + (f", {vm['n_unmapped']} could not be matched to an nflverse id" if vm.get("n_unmapped") else "") + ".</p>")
    elif vm:
        L.append(f"<p class='small muted'>Vacated share column unavailable: {esc(vm.get('reason'))}</p>")
    L.append(f"<p class='small muted'>Method: {esc(rec['method'])}</p>")
    c = ctx_completed_block or {}
    if c.get("week"):
        L.append(f"<h3>Last week (week {c['week']}): {esc(c.get('result'))}, {num(c.get('my_actual'))} vs {esc(c.get('opponent'))} {num(c.get('opponent_actual'))}"
                 f" <span class='muted small'>(projected {num(c.get('my_projected'))} vs {num(c.get('opponent_projected'))})</span></h3>")
        L.append("<details><summary>Player by player</summary><table><tr><th>Slot</th><th>Player</th><th>Pos</th><th class=n>Proj</th><th class=n>Actual</th><th class=n>Diff</th></tr>")
        for p in (c.get("starters") or []) + (c.get("bench") or []):
            d = p.get("diff")
            cls = "posv" if (d or 0) > 0 else "neg" if (d or 0) < 0 else ""
            L.append(f"<tr class='{'start' if p.get('slot') != 'BN' else ''}'><td>{esc(p.get('slot'))}</td><td>{esc(p.get('name'))}</td><td class=pos>{esc(p.get('pos'))}</td>"
                     f"<td class=n>{num(p.get('projected'))}</td><td class=n>{num(p.get('actual'))}</td><td class='n {cls}'>{num(d)}</td></tr>")
        L.append("</table></details>")
    L.append("</div>")
    return "".join(L)


def section_waivers(w):
    L = [f"<div class=card id=waivers><h2>Waivers and FAAB (week {w['week']})</h2>"]
    L.append(f"<p><b>Budget:</b> ${w['budget_left']} of ${w['budget_total']} left, {w['weeks_left']} weeks of season remaining. {esc(w['timing'])}</p>")
    if w["claims"]:
        L.append("<table><tr><th>#</th><th>Claim</th><th>Pos</th><th>Tm</th><th>Next opp</th><th class=n>Next wk proj</th><th class=n>Last wk actual</th>"
                 "<th class=n>Rest of season /wk</th><th class=n>Gain /wk</th><th>Drop</th><th class=n>Adds 72h</th><th class=n>Bid</th><th>Why</th></tr>")
        for i, c in enumerate(w["claims"], 1):
            L.append(f"<tr><td>{i}</td><td><b>{esc(c['name'])}</b> {inj_tag(c.get('injury_status'))}{' <span class=tag>starter</span>' if c.get('would_start') else ''}</td>"
                     f"<td class=pos>{esc(c['pos'])}</td><td>{esc(c['team'])}</td><td>{esc(c.get('opp_next') or '-')}</td><td class=n>{num(c.get('next_proj'))}</td>"
                     f"<td class=n>{num(c.get('last_actual'))}</td><td class=n>{num(c['ros'])}</td><td class='n {'posv' if c['gain'] > 0 else 'neg'}'>{c['gain']:+.1f}</td>"
                     f"<td>{esc(c['drop']['name'])} <span class=muted>({num(c['drop']['ros'])}/wk)</span></td><td class=n>{c['trending']:,}</td>"
                     f"<td class=n><span class=bid>${c['bid']}</span></td><td class=why>{esc(c['why'])}<br><i>Bid: {esc(c['bid_why'])}.</i></td></tr>")
        L.append("</table>")
    else:
        L.append("<p><b>No claim clears the bar this week.</b> Nobody on the wire adds more than half a point a week over your worst droppable player.</p>")
    if w["flyers"]:
        L.append("<h3>Popular adds that do not fit your roster</h3><ul class=tight>")
        for c in w["flyers"]:
            L.append(f"<li>{esc(c['name'])} ({esc(c['pos'])}, {esc(c['team'])}): {c['trending']:,} adds, but {esc(c['why'])}</li>")
        L.append("</ul>")
    L.append("<h3>Your drop order (lowest rest-of-season value first)</h3><ul class=tight>")
    for d in w["drop_candidates"]:
        L.append(f"<li>{esc(d['name'])} ({esc(d['pos'])}) {num(d['ros'])}/wk from {esc(d['ros_how'])}</li>")
    L.append("</ul><details><summary>Whole roster valued for the rest of the season</summary><table><tr><th>Player</th><th>Pos</th><th class=n>Next wk</th><th class=n>Rest of season /wk</th><th>Basis</th><th>Protected</th></tr>")
    for m in w["my_roster_values"]:
        L.append(f"<tr><td>{esc(m['name'])}</td><td class=pos>{esc(m['pos'])}</td><td class=n>{num(m.get('sleeper'))}</td><td class=n>{num(m['ros'])}</td><td class=small>{esc(m['ros_how'])}</td><td class=small>{esc(m.get('protected') or '')}</td></tr>")
    L.append("</table></details><details><summary>Assumptions behind the bids</summary><ul class=tight>")
    for a in w["assumptions"]:
        L.append(f"<li>{esc(a)}</li>")
    L.append(f"</ul><p class='small muted'>{w['all_evaluated']} unrostered players evaluated.</p></details></div>")
    return "".join(L)


def section_news(nz):
    m, s = nz["machine"], nz["synthesis"]
    L = ["<div class=card id=news><h2>News and injury zone</h2><div class=grid>"]
    L.append("<div class='card machine'><span class=label>Machine data, from Sleeper</span>")
    L.append(f"<p class='small muted'>{esc(m['source'])}. Table date {esc(m.get('date_central') or 'not yet pulled')}"
             + (f", {m['age_hours']} hours old" if m.get("age_hours") is not None else "") + f". {m['n_tracked']} rostered players tracked league-wide.</p>")
    if m["my_roster"]:
        L.append("<table><tr><th>Player</th><th>Slot</th><th>Status</th><th>Body</th><th>Practice</th><th>Since</th><th>News</th><th class=n>Depth</th><th>Changes (7 days)</th></tr>")
        for r in m["my_roster"]:
            hist = "<br>".join(esc(h) for h in r["history"]) or "<span class=muted>none</span>"
            L.append(f"<tr><td>{esc(r['name'])} <span class=pos>{esc(r['pos'])}</span></td><td>{esc(r['slot'])}</td><td>{inj_tag(r['injury_status']) or '<span class=muted>healthy</span>'}</td>"
                     f"<td>{esc(r.get('injury_body_part') or '')}</td><td class=small>{esc(r.get('practice_participation') or '')} {esc(r.get('practice_description') or '')}</td>"
                     f"<td class=small>{esc(r.get('injury_start_date') or '')}</td><td class=small>{esc(r.get('news_updated') or '')}"
                     + (f"<br><i>{esc(r.get('injury_notes'))}</i>" if r.get("injury_notes") else "") + f"</td><td class=n>{esc(r.get('depth_chart_order') if r.get('depth_chart_order') is not None else '')}</td><td class=small>{hist}</td></tr>")
        L.append("</table>")
    else:
        L.append("<p class=muted>No injury table yet. The daily 6 AM job creates it.</p>")
    if m["league_changes"]:
        L.append("<details><summary>League-wide injury changes, last 7 days</summary><ul class=tight>")
        for c in m["league_changes"]:
            f = "; ".join(f"{k.replace('_', ' ')}: {v.get('from') or 'none'} to {v.get('to') or 'none'}" for k, v in (c.get("fields") or {}).items())
            L.append(f"<li>{esc(c.get('date'))} {esc(c['name'])} ({esc(c['pos'])}, {esc(c['team_name'])}): {esc(f or c.get('kind'))}</li>")
        L.append("</ul></details>")
    L.append("</div>")
    L.append("<div class='card synth'><span class=label>Synthesis, written by the weekly Claude news pass</span>")
    if s["present"]:
        st = f"<span class='tag fail'>STALE, {s['age_days']} days old</span>" if s["stale"] else f"<span class='tag ok'>{s['age_days']} days old</span>" if s["age_days"] is not None else ""
        L.append(f"<p class='small muted'>Written {central(s.get('generated_at_utc'))} for week {esc(s.get('week'))}, source: {esc(s.get('source') or 'scheduled Claude task')}. {st}</p>")
        L.append(md_to_html(s["markdown"]))
    else:
        L.append("<p class=muted><b>No synthesis yet.</b> This box fills when the weekly scheduled Claude task (or the optional API step) commits data/synthesis/latest.md. "
                 "Until then only the machine half above is live. If this box is still empty two weeks after setup, the task is not running.</p>")
    L.append("</div></div></div>")
    return "".join(L)


def section_league(lv):
    L = [f"<div class=card id=league><h2>League view</h2>"]
    if lv["signals"]:
        L.append("<h3>Signals</h3><ul class=tight>")
        for s in lv["signals"]:
            L.append(f"<li><span class='tag {esc(s['severity'])}'>{esc(s['severity'])}</span> {esc(s['text'])}</li>")
        L.append("</ul>")
    L.append("<h3>Standings and trends</h3><table><tr><th class=n>Power</th><th>Team</th><th>Record</th><th>H2H</th>"
             + ("<th>Median</th>" if lv["median_game"] else "") +
             "<th>All-play</th><th class=n>Avg</th><th class=n>Last</th><th>Trend</th><th class=n>vs proj</th><th class=n>Lineup eff.</th><th>Injured starters</th><th>Byes next</th><th class=n>Proj next</th><th class=n>Sched left</th></tr>")
    for t in lv["teams"]:
        inj = ", ".join(f"{i['name']} ({i['status']})" for i in t["injured_starters"]) or "<span class=muted>none</span>"
        rec = f"{t['wins']}-{t['losses']}" + (f"-{t['ties']}" if t.get("ties") else "") if t.get("wins") is not None else "-"
        L.append(f"<tr class='{'mine' if t['is_mine'] else ''}'><td class=n>{t['power_rank']}</td><td><b>{esc(t['team'])}</b> <span class='muted small'>{esc(t['manager'])}</span></td>"
                 f"<td>{rec}</td><td>{esc(t['h2h'])}</td>" + (f"<td>{esc(t['median'])}</td>" if lv["median_game"] else "") +
                 f"<td>{esc(t['allplay'])}</td><td class=n>{num(t['avg'])}</td><td class=n>{num(t['last'])}</td><td>{esc(t['trend_label'])}"
                 + (f" ({t['trend']:+.1f})" if t.get("trend") is not None else "") + f"</td><td class=n>{num(t['vs_proj'])}</td>"
                 f"<td class=n>{(str(round(t['efficiency'] * 100)) + '%') if t.get('efficiency') else '-'}</td><td class=small>{inj}</td>"
                 f"<td class=small>{', '.join(t['byes_next']) or '<span class=muted>none</span>'}</td><td class=n>{num(t['proj_next'])}</td><td class=n>{num(t['sos_remaining'])}</td></tr>")
    L.append("</table>")
    L.append("<p class='small muted'>Power = 0.6 x season average + 0.4 x projected next week. All-play = record if you played every team every week (luck-free). "
             "vs proj = season points minus Sleeper's projection for the starters actually used. Lineup eff. = points scored / best possible lineup in hindsight. "
             "Sched left = average season score of remaining opponents.</p>")
    for n in lv["notes"]:
        L.append(f"<p class='small muted'>{esc(n)}</p>")
    L.append("</div>")
    return "".join(L)


def section_accuracy(acc):
    L = ["<div class=card id=accuracy><h2>Accuracy tracking</h2>"]
    for h in acc["honesty"]:
        L.append(f"<p><b>{esc(h)}</b></p>")
    L.append("<p class=small>Baselines: <b>Sleeper</b> = " + esc(acc["baselines"]["sleeper"]) + ". <b>Preseason</b> = " + esc(acc["baselines"]["preseason"])
             + ". <b>Naive</b> = " + esc(acc["baselines"]["naive"]) + ".</p>")
    weeks = acc.get("weeks") or []
    if weeks:
        L.append("<h3>Player level, every starter in the league that week</h3>"
                 "<table><tr><th>Week</th><th class=n>n</th><th class=n>Sleeper MAE</th><th class=n>Sleeper bias</th><th class=n>Sleeper rank corr</th>"
                 "<th class=n>Preseason MAE</th><th class=n>Preseason bias</th><th class=n>Preseason rank corr</th><th class=n>Naive MAE</th><th class=n>Naive bias</th><th class=n>Naive rank corr</th><th class=n>Sleeper from snapshot</th></tr>")
        for w in weeks:
            s = w["started"]
            L.append(f"<tr><td>{w['week']}</td><td class=n>{s['n_players']}</td>"
                     + "".join(f"<td class=n>{num(s[b]['mae'], 2)}</td><td class=n>{num(s[b]['bias'], 2)}</td><td class=n>{num(s[b]['spearman'], 3)}</td>" for b in ("sleeper", "preseason", "naive"))
                     + f"<td class=n>{s['sleeper_from_snapshot']} of {s['n_players']}</td></tr>")
        L.append("</table><p class='small muted'>MAE = average absolute miss in points. Bias = actual minus predicted (positive means the baseline ran low). Rank corr = Spearman correlation between predicted and actual order (1.0 is perfect).</p>")
        cut = acc.get("waiver_cut", 5.0)
        L.append(f"<h3>Player level, the waiver pool: players on nobody's roster that Sleeper projected at {cut:g}+ points</h3>"
                 "<table><tr><th>Week</th><th class=n>n</th><th class=n>Sleeper MAE</th><th class=n>Sleeper bias</th><th class=n>Sleeper rank corr</th>"
                 "<th class=n>Preseason MAE</th><th class=n>Preseason bias</th><th class=n>Preseason rank corr</th><th class=n>Naive MAE</th><th class=n>Naive bias</th><th class=n>Naive rank corr</th><th class=n>Sleeper from snapshot</th></tr>")
        for w in weeks:
            v = w.get("waiver") or {}
            if not v.get("n_players"):
                L.append(f"<tr><td>{w['week']}</td><td class=n>0</td><td class=n colspan=10 class=muted>no non-rostered player cleared the cut</td></tr>")
                continue
            L.append(f"<tr><td>{w['week']}</td><td class=n>{v['n_players']}</td>"
                     + "".join(f"<td class=n>{num(v[b]['mae'], 2)}</td><td class=n>{num(v[b]['bias'], 2)}</td><td class=n>{num(v[b]['spearman'], 3)}</td>" for b in ("sleeper", "preseason", "naive"))
                     + f"<td class=n>{v['sleeper_from_snapshot']} of {v['n_players']}</td></tr>")
        L.append(f"</table><p class='small muted'>These are the projections the FAAB bids are priced from, so they are now graded like the "
                 f"rostered ones. Free agents are a different population from starters (more part-time roles, more zeroes); read this table "
                 f"against itself week to week rather than against the starter table.</p>")
        L.append("<h3>Lineup level, all 12 rosters: points the lineup each baseline would have started</h3>"
                 "<table><tr><th>Week</th><th class=n>Managers actually scored</th><th class=n>% of optimal</th><th class=n>Sleeper lineup</th><th class=n>% opt</th><th class=n>vs manager</th>"
                 "<th class=n>Preseason lineup</th><th class=n>% opt</th><th class=n>vs manager</th><th class=n>Naive lineup</th><th class=n>% opt</th><th class=n>vs manager</th><th class=n>Your lineup / Sleeper / Preseason / Optimal</th></tr>")
        for w in weeks:
            lu = w["lineups"]
            cells = ""
            for b in ("sleeper", "preseason", "naive"):
                x = lu.get(b)
                cells += (f"<td class=n>{num(x['avg_points'])}</td><td class=n>{num(x['pct_of_optimal'])}%</td><td class=n>{x['vs_manager']:+.1f}</td>" if x else "<td class=n>-</td><td class=n>-</td><td class=n>-</td>")
            m = w.get("mine") or {}
            L.append(f"<tr><td>{w['week']}</td><td class=n>{num(lu['manager']['avg_points'])}</td><td class=n>{num(lu['manager']['pct_of_optimal'])}%</td>{cells}"
                     f"<td class=n>{num(m.get('actual'))} / {num(m.get('sleeper'))} / {num(m.get('preseason'))} / {num(m.get('optimal'))}</td></tr>")
        L.append("</table>")
        w = weeks[-1]
        db, cov = w["def_bias"], w["coverage"]
        L.append(f"<h3>Week {w['week']} checks</h3><ul class=tight>"
                 f"<li><b>DEF bias:</b> across {db['n']} defenses actual minus projected averaged {num(db['bias'], 2)} (MAE {num(db['mae'], 2)}); "
                 f"the two categories Sleeper never projects (3-and-outs, 4th-down stops) were worth {num(db['unprojected_pts'], 2)} per defense. Started defenses only: bias {num(db.get('started_bias'), 2)} over {db.get('started_n')}.</li>"
                 f"<li><b>Pre-kickoff coverage:</b> {cov['starters_with_snapshot']} of {cov['starters']} league starters had a frozen pre-kickoff projection.</li>"
                 f"<li><b>Post-hoc drift:</b> " + (f"Wednesday's stored projection differed from the frozen snapshot by {num(cov['posthoc_drift_mae'], 2)} on average over {cov['posthoc_drift_n']} players." if cov.get("posthoc_drift_n") else "not measurable yet (needs a week with both a snapshot and a Wednesday pull).") + "</li></ul>")
        p = acc.get("pooled") or {}
        if p.get("started") and len(weeks) > 1:
            L.append("<h3>Pooled over all weeks</h3><table><tr><th>Pool</th><th>Baseline</th><th class=n>Weeks</th><th class=n>n</th><th class=n>MAE</th><th class=n>Bias</th><th class=n>Lineup avg</th><th class=n>% of optimal</th><th class=n>vs manager</th></tr>")
            for lvl in (acc.get("pools") or ["started", "rostered", "waiver"]):
                for b in ("sleeper", "preseason", "naive"):
                    st = (p.get(lvl) or {}).get(b) or {}
                    lu = ((p.get("lineups") or {}).get(b) or {}) if lvl == "started" else {}
                    L.append(f"<tr><td>{esc(lvl)}</td><td>{b}</td><td class=n>{st.get('weeks', 0)}</td><td class=n>{st.get('n', 0)}</td>"
                             f"<td class=n>{num(st.get('mae'), 2)}</td><td class=n>{num(st.get('bias'), 2)}</td>"
                             f"<td class=n>{num(lu.get('avg_points'))}</td><td class=n>{num(lu.get('pct_of_optimal'))}</td><td class=n>{num(lu.get('vs_manager'))}</td></tr>")
            L.append("</table><p class='small muted'>Lineup columns apply to the started pool only; the rostered and waiver pools are player-level accuracy.</p>")
    elif acc.get("fallback"):
        f = acc["fallback"]
        L.append(f"<h3>Week {f['week']}, {esc(f['scope'])}, n = {f['n']} players</h3><table><tr><th>Baseline</th><th class=n>n</th><th class=n>MAE</th><th class=n>Bias</th><th class=n>Rank corr</th></tr>")
        for b in ("sleeper", "preseason", "naive"):
            s = f[b]
            L.append(f"<tr><td>{b}</td><td class=n>{s['n']}</td><td class=n>{num(s['mae'], 2)}</td><td class=n>{num(s['bias'], 2)}</td><td class=n>{num(s['spearman'], 3)}</td></tr>")
        L.append("</table><p class='small muted'>League-wide player and lineup metrics start with the first v1.2 pull (Wednesday), which stores every team's roster and every player's points.</p>")
    else:
        L.append("<p class=muted>No completed week scored yet.</p>")
    L.append("</div>")
    return "".join(L)


def section_keepers(kp, bt):
    L = [f"<div class=card id=keepers><h2>Keepers and trade value</h2>"]
    if kp.get("rows"):
        L.append(f"<p><b>Current top two by keeper surplus:</b> {esc(', '.join(kp['top2']))}.</p>")
        L.append("<table><tr><th>#</th><th>Player</th><th>Pos</th><th class=n>Age</th><th>2026 cost</th><th class=n>Rest of season /wk</th><th class=n>2027 est. /wk</th><th class=n>Slot normally buys</th><th class=n>Surplus /wk</th><th>Why</th></tr>")
        for r in kp["rows"]:
            L.append(f"<tr><td>{r['rank']}</td><td>{esc(r['name'])}{' <span class=tag>kept</span>' if r.get('kept_2026') else ''}</td><td class=pos>{esc(r['pos'])}</td><td class=n>{esc(r.get('age') or '')}</td>"
                     f"<td>{esc(r['cost_pick'])}</td><td class=n>{num(r['ros'])}</td><td class=n>{num(r['proj_2027'])}</td><td class=n>{num(r['slot_baseline'])}</td>"
                     f"<td class='n {'posv' if (r['surplus'] or 0) > 0 else 'neg'}'>{num(r['surplus'])}</td><td class=why>{esc(r['why'])}</td></tr>")
        L.append("</table>")
    else:
        L.append("<p class=muted>No roster loaded.</p>")
    for n in kp.get("notes") or []:
        L.append(f"<p class='small muted'>{esc(n)}</p>")
    L.append("</div>")
    return "".join(L)


def _md_table(rows, cols):
    """rows: list of dicts; cols: list of (key, header, decimals or None)."""
    h = ["<div class=tw><table><tr>" + "".join(f"<th{' class=n' if d is not None else ''}>{esc(hd)}</th>" for _, hd, d in cols) + "</tr>"]
    for r in rows:
        cells = []
        for k, _, d in cols:
            v = r.get(k)
            cells.append(f"<td class=n>{num(v, d)}</td>" if d is not None else f"<td>{esc(v)}</td>")
        h.append("<tr>" + "".join(cells) + "</tr>")
    h.append("</table></div>")
    return "".join(h)


def section_backtest(bt, hist):
    L = ["<div class=card id=backtest><h2>Backtest</h2>"]
    L.append("<h3>In-season backtest (this league's frozen snapshots)</h3>")
    L.append(f"<p class=small>{esc(bt.get('verdict'))} Full table in <code>data/derived/backtest.md</code>.</p>")
    rows = bt.get("table") or []
    if rows:
        L.append("<details><summary>Candidate table</summary>" + _md_table(rows, [("model", "Model", None), ("weeks", "Weeks", 0), ("n", "n", 0), ("mae", "Player MAE", 2), ("lineup_avg", "Lineup pts / team", 2)]) + "</details>")
    L.append("<h3>Historical backtest (nflverse, ten seasons, PSL scoring)</h3>")
    if not hist:
        L.append("<p class=muted><b>Not run yet.</b> <code>python engine.py histbacktest</code> writes <code>data/derived/hist_backtest.json</code> and this section fills from it. "
                 "It runs beside the in-season backtest and answers the sample-size questions that one cannot.</p></div>")
        return "".join(L)
    L.append(f"<p class='small muted'>Generated {central(hist.get('generated_at_utc'))}. {esc(hist.get('scope_line'))}</p>")
    for h in hist.get("headline") or []:
        L.append(f"<p><b>{esc(h)}</b></p>")
    for blk in hist.get("blocks") or []:
        L.append(f"<h4>{esc(blk.get('title'))}</h4>")
        if blk.get("text"):
            L.append(f"<p class=small>{esc(blk['text'])}</p>")
        if blk.get("rows") and blk.get("cols"):
            L.append(_md_table(blk["rows"], [(c[0], c[1], c[2] if len(c) > 2 else None) for c in blk["cols"]]))
        for n in blk.get("notes") or []:
            L.append(f"<p class='small muted'>{esc(n)}</p>")
    L.append("<p class='small muted'>Full write-up: <code>data/derived/hist_backtest.md</code> in the repo.</p></div>")
    return "".join(L)


def wrap_tables(html_s):
    """Wrap every table not already wrapped so wide tables scroll inside their own box on a phone."""
    out = html_s.replace("<div class=tw><table>", "\x00TW\x00")
    out = out.replace("<table>", "<div class=tw><table>").replace("</table>", "</table></div>")
    out = out.replace("\x00TW\x00", "<div class=tw><table>")
    # tables that were already wrapped now have a double closing div; collapse it
    return out.replace("</table></div></div>", "</table></div>")


def section_snapshots(ctx_snaps, upcoming):
    L = ["<div class=card id=snapshots><h2>Pre-kickoff snapshots</h2>"]
    if not ctx_snaps:
        L.append("<p class=muted><b>None captured yet.</b> The first fires Thursday 6 PM Central. If this list is still empty after a Sunday, the snapshot job is not running and the season's accuracy data is not being frozen.</p>")
    else:
        L.append("<table><tr><th>Week</th><th>Taken (Central)</th><th>Label</th><th class=n>Players</th><th class=n>NFL teams already started</th><th class=n>Still pre-kickoff</th></tr>")
        for s in reversed(ctx_snaps[-30:]):
            L.append(f"<tr><td>{s.get('week')}</td><td>{central(s.get('taken_at_utc'))}</td><td>{esc(s.get('label'))}</td><td class=n>{s.get('n_players')}</td><td class=n>{s.get('n_teams_started')}</td><td class=n>{s.get('n_players_pre_kickoff')}</td></tr>")
        L.append("</table>")
    L.append("<p class='small muted'>Schedule (Central): Thu, Sat, Sun, Mon at 10:30 AM and 6 PM, plus Sun 7:30 AM for London-window games. A snapshot only counts as pre-kickoff for a player whose NFL team had no stats yet when it was taken, so a late run can never contaminate the accuracy data.</p></div>")
    return "".join(L)


def section_validation(checks):
    L = ["<div class=card id=validation><h2>Data validation</h2><table><tr><th>Status</th><th>Check</th><th>Finding</th></tr>"]
    for c in checks:
        L.append(f"<tr><td><span class='tag {esc(c['status'])}'>{STATUS_ICON.get(c['status'], c['status'])}</span></td><td><b>{esc(c['title'])}</b></td><td class=small>{esc(c['finding'])}</td></tr>")
    L.append("</table></div>")
    return "".join(L)


def jobs_strip(status, ctx_now):
    labels = [("pull", "Weekly pull (Wed 10 AM)"), ("injuries", "Injury tracker (daily 6 AM)"), ("snapshot", "Pre-kickoff snapshot"),
              ("build", "Dashboard build"), ("synthesis", "News synthesis (weekly)")]
    L = ["<div class=jobs>"]
    tasks = status.get("tasks") or {}
    for key, label in labels:
        rec = tasks.get(key)
        if not rec:
            L.append(f"<div class='job none'><b>never run</b>{esc(label)}</div>")
            continue
        cls = "ok" if rec.get("ok") else "fail"
        when = central(rec.get("finished_utc"))
        L.append(f"<div class='job {cls}' title='{esc(rec.get('summary'))}'><b>{'OK' if rec.get('ok') else 'FAILED'} {when}</b>{esc(label)}</div>")
    L.append("</div>")
    failed = [t for t in tasks.values() if not t.get("ok")]
    return "".join(L), failed


def render(page, archive=False):
    ctx = page["ctx"]
    built = page["built_at_utc"]
    title = f"PSL Engine, week {ctx.upcoming_week}" + (" archive" if archive else "")
    jobs_html, failed = jobs_strip(ctx.status, ctx.now)
    banner = ""
    if failed and not archive:
        names = ", ".join(f"{t['task']} ({central(t.get('finished_utc'))})" for t in failed)
        banner = f"<div class='banner warnb show'>A scheduled job failed on its last run: {esc(names)}. The sections that depend on it may be stale. Details in the GitHub Actions log.</div>"
    archives = page.get("archives") or []
    arch_links = " ".join(f"<a href='{esc(a['href'])}'>week {a['week']}</a>" for a in archives)
    completed = ctx.latest.get("completed_week")
    # Tabs. Every panel is in the HTML; the script only toggles which one is visible.
    tabs = [
        ("tab-lineup", "Lineup", section_lineup(page["lineup"], completed)),
        ("tab-waivers", "Waivers", section_waivers(page["waivers"])),
        ("tab-league", "League", section_league(page["league"]) + section_keepers(page.get("keepers") or {}, page.get("backtest") or {})),
        ("tab-news", "News and injuries", section_news(page["news"])),
        ("tab-accuracy", "Accuracy", section_accuracy(page["accuracy"]) + section_snapshots(ctx.snap_index, ctx.upcoming_week) + section_validation(page["validation"])),
        ("tab-backtest", "Backtest", section_backtest(page.get("backtest") or {}, page.get("hist_backtest"))),
    ]
    tabbar = ["<nav class=tabbar role=tablist aria-label='Dashboard sections'>"]
    for tid, label, _ in tabs:
        tabbar.append(f"<a class=tab role=tab href='#{tid}' data-tab='{tid}' aria-controls='{tid}'>{esc(label)}</a>")
    tabbar.append("<button type=button class='tab all' id=tab-all aria-pressed=false>Show everything</button></nav>")
    panels = []
    for tid, label, body_html in tabs:
        panels.append(f"<section class=panel id='{tid}' role=tabpanel aria-label='{esc(label)}'>{wrap_tables(body_html)}</section>")
    H = [f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{esc(title)}</title><meta name=viewport content='width=device-width,initial-scale=1'>"
         f"<meta name=color-scheme content='light dark'><style>{CSS}</style></head>",
         f"<body data-built='{esc(built)}' data-stale-hours='{config.STALE_AFTER_HOURS}' data-archive='{1 if archive else 0}'><div class=wrap>",
         f"<div class=top><div><h1>{esc(ctx.meta.get('league') or 'Pretend Sportsball League')}: weekly engine</h1>"
         f"<div class='small muted'>Built {central(built)} from data pulled {central(ctx.meta.get('pulled_at_utc'))}. Completed week {ctx.completed_week}, upcoming week {ctx.upcoming_week}. "
         f"{'Self-contained archive for week ' + str(ctx.upcoming_week) + '. ' if archive else ''}Engine v{config.ENGINE_VERSION}.</div></div>"
         f"<div id=age class=age>Data age: computing</div></div>",
         "<div id=stale-banner class=banner></div>", banner, jobs_html,
         "".join(tabbar),
         "".join(panels),
         f"<p class=foot>" + (f"<span class=muted>Archives:</span> {arch_links} " if arch_links else "") + f"<a href='{config.REPO_URL}' target=_blank rel=noopener>repo</a> "
         f"<a href='{config.REPO_URL}/tree/main/data' target=_blank rel=noopener>data folder</a> <span class=muted>All numbers on this page are inlined at build time; nothing is fetched live. "
         f"Method notes: docs/METHOD.md in the repo. Bookmark a tab with its # link, for example #tab-waivers.</span></p>",
         f"<script type='application/json' id='engine-data'>{json.dumps(page['payload'], separators=(',', ':')).replace('</', '<\\/')}</script>",
         f"<script>{JS}</script></div></body></html>"]
    return "".join(H)
