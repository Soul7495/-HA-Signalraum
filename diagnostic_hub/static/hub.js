'use strict';
(() => {
  const q = selector => document.querySelector(selector);
  const base = new URL(document.querySelector('base').href);
  const node = (tag, cls, text) => { const n = document.createElement(tag); n.className = cls || ''; if (text != null) n.textContent = text; return n; };
  const when = t => new Date(t * 1000).toLocaleString('de-DE');
  const labels = {running:'Aufnahme läuft',complete:'Beendet',incomplete:'Beendet · Datenlücke',stopped:'Manuell beendet',storage_full:'Speichergrenze erreicht',storage_error:'Speicherfehler'};
  let sources = [], sourceSignature = '', listSignature = '', pending = false, timer, refreshController;
  let requestId = window.diagnosticRuntime.requestId();
  const params = new URLSearchParams(location.search);
  let recPage = Math.max(1, Number(params.get('record_page')) || 1);
  const form = q('#record-form');
  async function api(path, body, signal) {
    const scope = window.diagnosticRuntime.requestScope(signal);
    const options = {cache:'no-store',credentials:'same-origin',signal:scope.signal};
    if (body) Object.assign(options,{method:'POST',headers:{'Content-Type':'application/json','X-Diagnostic-Hub':'1'},body:JSON.stringify(body)});
    let response;
    try {
      response = await fetch(new URL(path,base),options);
      // Read within the same timeout, including slow response bodies.
      const data = await response.arrayBuffer();
      response = new Response(data,{status:response.status,headers:response.headers});
    } finally { scope.close(); }
    if (!response.ok) {
      let message = 'Anfrage fehlgeschlagen. Verbindung und Aufnahmestatus prüfen.';
      try { message = (await response.json()).error || message; } catch (_) { /* readable fallback */ }
      throw new Error(message);
    }
    return response;
  }
  function persistSource() {
    params.set('source',q('#record-source').value); params.set('level',q('#record-level').value); params.set('record_page',String(recPage));
    window.diagnosticQuery({source:q('#record-source').value,level:q('#record-level').value,record_page:recPage});
  }
  function selected() {
    const source = sources.find(s=>s.id === q('#record-source').value);
    q('#breadcrumb').textContent = source ? `${source.name} / ${source.stream} / Zeitfenster` : 'QUELLE / LOGS / ZEITFENSTER';
    q('#source-help').textContent = source ? source.description : 'Logquelle auswählen. Logstufen änderst du in der jeweiligen App.';
    q('#preview').disabled = !source;
    q('#preview-panel').hidden = true;
    for (const button of q('#source-tree').querySelectorAll('button')) button.setAttribute('aria-pressed',String(button.dataset.source===source?.id));
    persistSource();
  }
  function chooseApp(preferredSource='') {
    const app = q('#record-app').value;
    const select = q('#record-source');
    const options = sources.filter(source=>source.id===app);
    select.replaceChildren(new Option('Logquelle auswählen',''));
    for (const source of options) select.add(new Option(source.stream,source.id));
    if (options.some(source=>source.id===preferredSource)) select.value=preferredSource;
    else if (options.length===1) select.value=options[0].id;
    select.disabled=!options.length;
    selected();
  }
  function renderSources(data) {
    sources = data.items;
    const installed = sources.filter(source=>source.kind==='addon').length;
    q('#discovery-info').textContent = `${installed} installierte Apps · ${sources.length} Logquellen · zuletzt geprüft ${when(data.checked_at)}`;
    q('#discovery-error').hidden=!data.error;
    q('#discovery-error').textContent=data.error ? 'App-Erkennung fehlgeschlagen: '+data.error+' Die direkte evcc-API ist keine automatisch erkannte App.' : '';
    const signature = JSON.stringify(sources);
    if (signature === sourceSignature || ['record-app','record-source'].includes(document.activeElement?.id)) return;
    sourceSignature = signature;
    const value = q('#record-source').value || params.get('source');
    const app = q('#record-app'); app.replaceChildren(new Option('App auswählen',''));
    const groups = {addon:new OptGroup('Installierte Apps'),core:new OptGroup('Home Assistant'),api:new OptGroup('Manuell konfigurierte Verbindungen')};
    function OptGroup(label){ const group=document.createElement('optgroup');group.label=label;return group; }
    const tree = q('#source-tree'); const opened = new Set([...tree.querySelectorAll('details[open]')].map(d=>d.dataset.id)); tree.replaceChildren();
    for (const source of sources) {
      groups[source.kind].append(new Option(source.name,source.id));
      const group = node('details','source-group'); group.dataset.id=source.id; group.open=opened.has(source.id);
      group.append(node('summary','',source.name),node('span','source-label',source.kind==='addon' ? `Installierte App · ${source.state}` : source.kind==='core' ? 'Home Assistant' : 'Manuell konfigurierte API · Verbindung nicht automatisch bestätigt'));
      const button=node('button','',source.name+' auswählen');button.type='button';button.dataset.source=source.id;button.setAttribute('aria-pressed',String(source.id===value));
      button.addEventListener('click',()=>{app.value=source.id;chooseApp(source.id);if(!pending)requestId=window.diagnosticRuntime.requestId();app.focus();});group.append(button);tree.append(group);
    }
    for(const group of Object.values(groups)) if(group.children.length) app.append(group);
    if (!installed) tree.prepend(node('p','muted',data.error ? 'Keine installierten Apps abrufbar. Siehe Fehlermeldung oben.' : 'Der Supervisor meldet keine weiteren installierten Apps. Integrationen sind keine separaten Apps.'));
    if (sources.some(source=>source.id===value)) app.value=value;
    chooseApp(value);
  }
  function card(item) {
    const article = node('article','case record-card');
    const top=node('div','case-top'); top.append(node('h3','',item.name),node('span','badge '+(item.state==='running'?'pending':item.gaps.length?'incomplete':'complete'),labels[item.state]||item.state));
    const meta=node('div','meta'); meta.append(node('span','',item.level+' und höher'),node('span','',`${item.count.toLocaleString('de-DE')} ${item.count===1?'Zeile':'Zeilen'}`),node('span','',`Prüfung alle ${item.interval} s`));
    article.append(top,node('p','muted',`Start: ${when(item.started)} · Geplantes Ende: ${when(item.deadline)}`),meta);
    if (item.state==='running') {
      const native=node('progress'); native.max=1; native.value=Math.min(1,Math.max(0,(Date.now()/1000-item.started)/(item.deadline-item.started))); native.setAttribute('aria-label','Vergangene Aufnahmedauer');
      article.append(native,node('p','muted',`Noch etwa ${Math.max(0,Math.ceil((item.deadline-Date.now()/1000)/60))} Minuten. Bereits gesicherte Daten sind herunterladbar.`));
    }
    if (!item.last_poll) article.append(node('p','muted','Erster erfolgreicher Abruf steht noch aus.'));
    if (item.error) article.append(node('p','gap',item.error));
    for (const gap of item.gaps) article.append(node('p','gap',gap));
    const actions=node('div','actions');
    for (const [gzip,label] of [[false,'Text herunterladen'],[true,'gzip herunterladen']]) {
      const a=node('a','action'+(!gzip?' primary':''),label); a.href=new URL(`api/recordings/${item.id}/download${gzip?'?gzip=1':''}`,base).href; a.download=`aufnahme-${item.id}.txt${gzip?'.gz':''}`; actions.append(a);
    }
    if (item.state==='running') {
      const stop=node('button','','Aufnahme beenden');stop.type='button';
      stop.addEventListener('click',async()=>{stop.disabled=true;try{await api(`api/recordings/${item.id}/stop`,{});q('#record-feedback').textContent='Aufnahme beendet. Bisherige Daten bleiben erhalten.';listSignature='';await refresh();}catch(e){q('#hub-error').hidden=false;q('#hub-error').textContent=e.message;stop.disabled=false;}});actions.append(stop);
    }
    article.append(actions);return article;
  }
  async function refresh(force=false) {
    clearTimeout(timer);
    refreshController?.abort(); refreshController=new AbortController(); const mine=refreshController;
    q('#discover').disabled=true;
    try {
      const [catalog,summary,recordings] = await Promise.all([api('api/sources'+(force?'?refresh=1':''),null,mine.signal).then(r=>r.json()),api('api/hub',null,mine.signal).then(r=>r.json()),api('api/recordings?page='+recPage,null,mine.signal).then(r=>r.json())]);
      if (mine!==refreshController) return;
      renderSources(catalog);
      q('#hub-status').textContent=`${summary.active} ${summary.active===1?'aktive Aufnahme':'aktive Aufnahmen'} · ${(summary.bytes/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})} / ${(summary.limit_bytes/1048576).toLocaleString('de-DE')} MiB · ${summary.active ? 'Aufnahmen enden zum geplanten Zeitpunkt.' : 'Keine manuelle Aufnahme läuft.'}`;
      q('#hub-error').hidden=!summary.warning; q('#hub-error').textContent=summary.warning;
      q('#automatic-state').textContent=summary.automatic_evcc_enabled?'Automatische evcc-Fehlersicherung ist zusätzlich aktiv.':'Automatische evcc-Fehlersicherung ist aus. Bisherige Fälle bleiben verfügbar. Aktivierung in der Add-on-Konfiguration.';
      recPage=recordings.page;persistSource();
      const signature=JSON.stringify(recordings);
      if(signature!==listSignature&&!q('#recordings-list').contains(document.activeElement)) {
        listSignature=signature;q('#recordings-list').replaceChildren(...recordings.items.map(card));
        if (!recordings.items.length) q('#recordings-list').append(node('p','empty','Noch keine manuelle Aufnahme. Wähle eine Logquelle und starte dein Zeitfenster.'));
      }
      q('#record-range').textContent=`Seite ${recPage} von ${recordings.pages} · ${recordings.total} ${recordings.total===1?'Aufnahme':'Aufnahmen'}`;
      q('#record-prev').disabled=recPage<=1;q('#record-next').disabled=recPage>=recordings.pages;
    } catch(e) { if(mine===refreshController){q('#hub-error').hidden=false;q('#hub-error').textContent=e.message;} }
    finally {if(mine===refreshController){q('#discover').disabled=false;q('#recordings-list').setAttribute('aria-busy','false');timer=setTimeout(refresh,10000);}}
  }
  form.addEventListener('input',()=>{if(!pending) requestId=window.diagnosticRuntime.requestId();});
  q('#record-app').addEventListener('change',()=>chooseApp());
  q('#record-source').addEventListener('change',selected);q('#record-level').addEventListener('change',persistSource);
  if(['TRACE','DEBUG','INFO','WARN','ERROR'].includes(params.get('level'))) q('#record-level').value=params.get('level');
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(pending)return;
    const error=q('#form-error');error.hidden=true;
    for(const input of form.querySelectorAll('[aria-invalid]')) input.removeAttribute('aria-invalid');
    const hours=Number(q('#record-hours').value),interval=Number(q('#record-interval').value);
    let invalid=!q('#record-app').value?q('#record-app'):!q('#record-source').value?q('#record-source'):!Number.isFinite(hours)||hours<0.25||hours>168||!Number.isInteger(hours*60)?q('#record-hours'):!Number.isInteger(interval)||interval<10||interval>300?q('#record-interval'):null;
    if(invalid){error.hidden=false;error.textContent='Logquelle auswählen, Dauer zwischen 0,25 und 168 Stunden und Prüfintervall zwischen 10 und 300 Sekunden eintragen.';invalid.setAttribute('aria-invalid','true');invalid.focus();return;}
    const body={request_id:requestId,source:q('#record-source').value,level:q('#record-level').value,duration_minutes:Math.round(hours*60),poll_seconds:interval,include_history:q('#record-history').checked};
    pending=true;q('#record-fields').disabled=true;q('#start-recording').setAttribute('aria-busy','true');
    try{const result=await (await api('api/recordings',body)).json();q('#record-feedback').textContent=`Aufnahme gestartet: ${result.name}, Ende ${when(result.deadline)}. Logstufen bleiben unverändert.`;requestId=window.diagnosticRuntime.requestId();recPage=1;listSignature='';await refresh();}
    catch(e){error.hidden=false;error.textContent=e.message;}
    finally{pending=false;q('#record-fields').disabled=false;q('#start-recording').setAttribute('aria-busy','false');}
  });
  q('#preview').addEventListener('click',async()=>{
    const button=q('#preview');button.disabled=true;
    const path='api/snapshot?source='+encodeURIComponent(q('#record-source').value)+'&level='+q('#record-level').value;
    try{const text=await (await api(path)).text();q('#preview-log').textContent=text.split('\n').slice(-200).join('\n');q('#preview-panel').hidden=false;q('#preview-panel').open=true;q('#snapshot-download').href=new URL(path,base).href;q('#record-feedback').textContent='Puffer abgerufen. Vorschau zeigt maximal die letzten 200 Zeilen; der Download enthält den verfügbaren Puffer.';}
    catch(e){q('#form-error').hidden=false;q('#form-error').textContent=e.message;}
    finally{button.disabled=false;}
  });
  q('#discover').addEventListener('click',()=>refresh(true));
  q('#record-prev').addEventListener('click',()=>{recPage--;refresh();});q('#record-next').addEventListener('click',()=>{recPage++;refresh();});
  window.addEventListener('pagehide',()=>{clearTimeout(timer);refreshController?.abort();});
  refresh();
})();
