'use strict';
const $ = selector => document.querySelector(selector);
const base = new URL(document.querySelector('base').href);
const params = new URLSearchParams(location.search);
let page = Math.max(1, Number(params.get('page')) || 1);
let controller;
let timer;
const formatNumber = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 });
const date = value => value ? new Date(value).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'medium' }) : 'Noch kein erfolgreicher Abruf';
const labels = { pending: 'Nachlauf läuft', complete: 'Abgeschlossen', incomplete: 'Mit Datenlücke', legacy: 'Altbestand' };
const element = (tag, className, text) => { const node = document.createElement(tag); node.className = className || ''; if (text != null) node.textContent = text; return node; };
async function get(url, signal) {
  const response = await fetch(new URL(url, base), { signal, cache: 'no-store', credentials: 'same-origin' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response;
}
function caseCard(item) {
  const card = element('article', 'case');
  const top = element('div', 'case-top');
  top.append(element('h3', '', item.category || 'evcc'), element('span', 'badge ' + item.status, labels[item.status] || 'Unbekannt'));
  const meta = element('div', 'meta');
  meta.append(element('span', '', date(item.time)), element('span', '', `${item.repeats == null ? 'Unbekannte Anzahl' : formatNumber.format(item.repeats) + (item.repeats === 1 ? ' Beobachtung' : ' Beobachtungen')}`), element('span', '', `${formatNumber.format(item.bytes / 1024)} KiB`));
  const detail = element('details');
  detail.append(element('summary', '', 'Sicherungsdetails'));
  detail.append(element('p', '', `Quelle: ${item.source} · Vorgeschichte: ${item.pre_lines ?? 'unbekannt'} Zeilen · Nachlauf: ${item.post_lines ?? 'unbekannt'} Zeilen`));
  if (item.deadline) detail.append(element('p', '', `Nachlauf vorgesehen bis ${date(new Date(item.deadline * 1000).toISOString())}`));
  if (item.origin && item.origin !== 'new') detail.append(element('p', '', item.origin === 'initial' ? 'Ausgangssnapshot: Der Fehler kann schon vor dem ersten Abruf aufgetreten sein.' : item.origin === 'collector' ? 'Die Datenquelle war nicht erreichbar. Vorgeschichte aus dem letzten erfolgreichen Abruf dieser Sitzung.' : 'Neu eingelesener Puffer nach fehlender Überlappung.'));
  for (const gap of item.gaps || []) detail.append(element('p', '', gap));
  const actions = element('div', 'actions');
  const path = 'api/download/' + encodeURIComponent(item.filename);
  for (const [suffix, label, primary] of [['?format=txt', 'Text herunterladen', true], ['', 'Original', false]]) {
    const link = element('a', 'action' + (primary ? ' primary' : ''), label);
    link.href = new URL(path + suffix, base).href;
    link.download = suffix ? item.filename.split('.')[0] + '.txt' : item.filename;
    actions.append(link);
  }
  // Two gestures: prepare the file first, then share with a fresh user activation.
  const probe = new File([''], 'diagnose.txt', { type: 'text/plain' });
  if (navigator.canShare && navigator.canShare({ files: [probe] })) {
    const share = element('button', '', 'Teilen vorbereiten'); share.type = 'button';
    const status = element('span', 'share-status'); status.setAttribute('role', 'status');
    let file;
    share.addEventListener('click', async () => {
      if (file) {
        try { await navigator.share({ files: [file], title: 'Diagnostic Hub' }); }
        catch (error) { if (error.name !== 'AbortError') status.textContent = 'Teilen nicht möglich. Verwende Text herunterladen.'; }
        return;
      }
      share.disabled = true; status.textContent = 'Text wird vorbereitet …';
      try {
        const response = await get(path + '?format=txt', AbortSignal.timeout(20000));
        file = new File([await response.blob()], item.filename.split('.')[0] + '.txt', { type: 'text/plain' });
        share.textContent = 'Teilen öffnen'; status.textContent = 'Datei bereit. Jetzt Teilen öffnen wählen.';
      } catch (error) { status.textContent = 'Vorbereitung fehlgeschlagen. Erneut versuchen oder Text herunterladen.'; }
      finally { share.disabled = false; }
    });
    actions.append(share, status);
  }
  card.append(top, element('p', 'trigger', item.trigger), meta, detail, actions);
  return card;
}
async function update() {
  clearTimeout(timer);
  if (controller) controller.abort();
  controller = new AbortController();
  const current = controller;
  const timeout = setTimeout(() => current.abort('timeout'), 20000);
  $('#refresh').disabled = true;
  $('#refresh').setAttribute('aria-busy', 'true');
  $('#list').setAttribute('aria-busy', 'true');
  try {
    const [status, cases] = await Promise.all([
      get('api/status', current.signal).then(r => r.json()),
      get('api/incidents?page=' + page, current.signal).then(r => r.json())
    ]);
    if (controller !== current) return;
    $('#health').textContent = status.health;
    $('#last-success').textContent = 'Letzter Abruf: ' + date(status.last_success);
    $('#count').textContent = formatNumber.format(status.count);
    $('#pending').textContent = `${formatNumber.format(status.pending)} ${status.pending === 1 ? 'Nachlauf offen' : 'Nachläufe offen'}`;
    $('#storage').textContent = status.bytes < 1048576 ? formatNumber.format(status.bytes / 1024) + ' KiB' : formatNumber.format(status.bytes / 1048576) + ' MiB';
    $('#capacity').textContent = `Grenze: ${formatNumber.format(status.max_storage_mb)} MiB`;
    $('#notice').textContent = status.continuity;
    $('#error').hidden = !(status.warning || status.error);
    $('#error').textContent = [status.warning, status.error].filter(Boolean).join(' ');
    $('#policy').textContent = `${status.retention_days} Tage Aufbewahrung · ${status.poll_seconds} Sekunden Prüfintervall · gzip ${status.gzip_enabled ? 'aktiv' : 'inaktiv'}`;
    // Preserve open details, focus and prepared share files on background refresh.
    const list = $('#list');
    const signature = JSON.stringify(cases);
    if (list.dataset.signature !== signature && !list.contains(document.activeElement)) {
      list.dataset.signature = signature;
      const opened = new Set([...list.querySelectorAll('details[open]')].map(n => n.closest('article').dataset.file));
      list.replaceChildren();
      if (!cases.items.length) list.append(element('p', 'empty', 'Noch kein Diagnosefall gespeichert. Der Logger sichert automatisch einen Block, sobald evcc einen relevanten Fehler liefert.'));
      for (const item of cases.items) { const card = caseCard(item); card.dataset.file = item.filename; card.querySelector('details').open = opened.has(item.filename); list.append(card); }
    }
    page = cases.page;
    params.set('page', String(page));
    history.replaceState(null, '', location.pathname + '?' + params.toString());
    $('#range').textContent = `Seite ${page} von ${cases.pages} · ${cases.total} ${cases.total === 1 ? 'Fall' : 'Fälle'}`;
    $('#prev').disabled = page <= 1;
    $('#next').disabled = page >= cases.pages;
  } catch (error) {
    if (controller !== current) return;
    $('#error').hidden = false;
    $('#error').textContent = 'Verbindung zur Oberfläche unterbrochen. Angezeigte Daten können veraltet sein. Prüfe Home Assistant und wähle Aktualisieren.';
  } finally {
    clearTimeout(timeout);
    if (controller === current) { $('#refresh').disabled = false; $('#refresh').setAttribute('aria-busy', 'false'); $('#list').setAttribute('aria-busy', 'false'); timer = setTimeout(update, 15000); }
  }
}
$('#refresh').addEventListener('click', update);
$('#prev').addEventListener('click', () => { page--; update(); });
$('#next').addEventListener('click', () => { page++; update(); });
window.addEventListener('pagehide', () => { clearTimeout(timer); controller?.abort(); });
update();
