/* CardScan — app.js */
'use strict';

let dataURL     = null;   // current image as base64 data-URL
let extracted   = {};     // last OCR result
let cards       = [];     // saved cards list
let liveStream  = null;   // getUserMedia stream

/* ── DOM ── */
const inpGallery = document.getElementById('inp-gallery');
const inpCamera  = document.getElementById('inp-camera');
const btnLive    = document.getElementById('btn-live');
const dropZone   = document.getElementById('drop-zone');
const prevWrap   = document.getElementById('prev-wrap');
const prevImg    = document.getElementById('prev-img');
const btnClear   = document.getElementById('btn-clear');
const btnScan    = document.getElementById('btn-scan');
const resultBox  = document.getElementById('result-box');
const resFields  = document.getElementById('res-fields');
const liveWrap   = document.getElementById('live-wrap');
const liveFeed   = document.getElementById('live-feed');
const btnSnap    = document.getElementById('btn-snap');
const snapCv     = document.getElementById('snap-cv');
const progBox    = document.getElementById('prog-box');
const progFill   = document.getElementById('prog-fill');
const progLbl    = document.getElementById('prog-lbl');
const toastEl    = document.getElementById('toast-msg');

/* ════════════════════════════════════════════
   TOAST
════════════════════════════════════════════ */
let toastTmr;
function toast(msg, type) {
  clearTimeout(toastTmr);
  toastEl.textContent = msg;
  toastEl.className   = 'show' + (type ? ' ' + type : '');
  toastTmr = setTimeout(() => { toastEl.className = ''; }, 3200);
}

/* ════════════════════════════════════════════
   SHOW PREVIEW
════════════════════════════════════════════ */
function showPreview(url) {
  dataURL = url;
  prevImg.src = url;
  prevWrap.style.display  = 'block';
  btnScan.disabled        = false;
  resultBox.style.display = 'none';
  stopLive();
}

/* ════════════════════════════════════════════
   FILE INPUTS
   Both inputs fire 'change' — we read the file
   with FileReader and call showPreview().
   Using <label for="..."> in HTML means the
   browser opens the picker natively on mobile
   without any JS .click() call.
════════════════════════════════════════════ */
function handleFileInput(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    toast('Please select an image file', 'err'); return;
  }
  const reader = new FileReader();
  reader.onload  = ev => showPreview(ev.target.result);
  reader.onerror = ()  => toast('Could not read file', 'err');
  reader.readAsDataURL(file);
  // Reset so the same file can be picked again next time
  e.target.value = '';
}

inpGallery.addEventListener('change', handleFileInput);
inpCamera.addEventListener('change',  handleFileInput);

/* ════════════════════════════════════════════
   DRAG & DROP  (desktop)
════════════════════════════════════════════ */
dropZone.addEventListener('dragover',  e => { e.preventDefault(); dropZone.classList.add('drag'); });
dropZone.addEventListener('dragleave', ()  => dropZone.classList.remove('drag'));
dropZone.addEventListener('drop', e => {
  e.preventDefault(); dropZone.classList.remove('drag');
  const file = [...(e.dataTransfer.files || [])].find(f => f.type.startsWith('image/'));
  if (file) { const r = new FileReader(); r.onload = ev => showPreview(ev.target.result); r.readAsDataURL(file); }
});

/* ════════════════════════════════════════════
   CLEAR
════════════════════════════════════════════ */
btnClear.addEventListener('click', () => {
  prevWrap.style.display  = 'none';
  prevImg.src = '';
  dataURL = null;
  btnScan.disabled        = true;
  resultBox.style.display = 'none';
  progBox.style.display   = 'none';
});

/* ════════════════════════════════════════════
   LIVE CAMERA  (getUserMedia)
   Good for desktop.  On mobile, most browsers
   require HTTPS for getUserMedia — that's why
   app.py runs over HTTPS.
════════════════════════════════════════════ */
btnLive.addEventListener('click', async () => {
  if (liveStream) { stopLive(); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    // No getUserMedia — trigger camera-input as fallback
    inpCamera.click(); return;
  }
  try {
    liveStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } }
    });
    liveFeed.srcObject    = liveStream;
    liveWrap.style.display = 'block';
    btnLive.querySelector('span').textContent = 'Stop';
  } catch (err) {
    console.warn('getUserMedia:', err.name);
    // Fallback: open camera input
    toast('Opening camera…');
    setTimeout(() => inpCamera.click(), 200);
  }
});

btnSnap.addEventListener('click', () => {
  if (!liveFeed.videoWidth) { toast('Camera not ready yet', 'err'); return; }
  snapCv.width  = liveFeed.videoWidth;
  snapCv.height = liveFeed.videoHeight;
  snapCv.getContext('2d').drawImage(liveFeed, 0, 0);
  showPreview(snapCv.toDataURL('image/jpeg', 0.93));
  toast('Photo captured!');
});

function stopLive() {
  if (liveStream) {
    liveStream.getTracks().forEach(t => t.stop());
    liveStream = null; liveFeed.srcObject = null;
  }
  liveWrap.style.display = 'none';
  const sp = btnLive.querySelector('span');
  if (sp) sp.textContent = 'Live';
}

/* ════════════════════════════════════════════
   SCAN  →  POST to Flask /scan
════════════════════════════════════════════ */
function startProgress() {
  let p = 0;
  progFill.style.width  = '0%';
  progBox.style.display = 'block';
  const iv = setInterval(() => {
    p = Math.min(p + Math.random() * 8, 88);
    progFill.style.width = p + '%';
    progLbl.textContent  =
      p < 30 ? 'Pre-processing image…' :
      p < 62 ? 'Running OCR engine…' : 'Extracting fields…';
  }, 260);
  return iv;
}

btnScan.addEventListener('click', async () => {
  if (!dataURL) return;
  btnScan.disabled  = true;
  btnScan.innerHTML = '<div class="spinner"></div>Scanning…';
  resultBox.style.display = 'none';

  const iv = startProgress();

  try {
    const res  = await fetch('/scan', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ imageData: dataURL })
    });

    clearInterval(iv);
    progFill.style.width = '100%';
    progLbl.textContent  = 'Done!';
    setTimeout(() => { progBox.style.display = 'none'; }, 500);

    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error || 'Scan failed');

    extracted = json.data;
    renderFields(extracted);
    resultBox.style.display = 'block';
    toast('Card scanned!', 'ok');

  } catch (err) {
    clearInterval(iv);
    progBox.style.display = 'none';
    toast('Error: ' + err.message, 'err');
    console.error(err);
  } finally {
    btnScan.disabled  = false;
    btnScan.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
      </svg>Scan Card`;
  }
});

/* ════════════════════════════════════════════
   RESULT FIELDS
════════════════════════════════════════════ */
const FIELD_DEFS = [
  { k:'cardType',    l:'Card Type' },
  { k:'name',        l:'Name' },
  { k:'title',       l:'Title' },
  { k:'company',     l:'Company' },
  { k:'phone',       l:'Phone' },
  { k:'email',       l:'Email' },
  { k:'website',     l:'Website' },
  { k:'address',     l:'Address' },
  { k:'socialMedia', l:'Social' },
  { k:'notes',       l:'Notes',   multi:true },
  { k:'rawText',     l:'Raw OCR', multi:true },
];

function renderFields(d) {
  resFields.innerHTML = FIELD_DEFS.filter(f => d[f.k]).map(f => `
    <div class="rf">
      <label>${f.l}</label>
      ${f.multi
        ? `<textarea id="f_${f.k}" rows="2">${he(d[f.k])}</textarea>`
        : `<input id="f_${f.k}" type="text" value="${ha(d[f.k])}">`}
    </div>`).join('');
}

function readFields() {
  const keys = ['cardType','name','title','company','phone','email','website','address','socialMedia','notes'];
  const out  = {};
  keys.forEach(k => {
    const el = document.getElementById('f_'+k);
    out[k] = el ? el.value.trim() : (extracted[k] || '');
  });
  return out;
}

function he(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function ha(s){ return (s||'').replace(/"/g,'&quot;'); }

/* ════════════════════════════════════════════
   SAVE CARD
════════════════════════════════════════════ */
document.getElementById('btn-save').addEventListener('click', async () => {
  const card = readFields();
  if (!card.name && !card.company && !card.phone) {
    toast('Fill at least name, company or phone', 'err'); return;
  }
  if (dataURL) card.image = dataURL;
  try {
    const res  = await fetch('/cards', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(card)
    });
    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error);
    toast('Card saved!', 'ok');
    resultBox.style.display = 'none';
    await loadCards();
  } catch (err) { toast('Save failed: ' + err.message, 'err'); }
});

/* ════════════════════════════════════════════
   SAVE TO CONTACTS  (VCF)
════════════════════════════════════════════ */
document.getElementById('btn-contact').addEventListener('click', () => {
  const card = readFields();
  if (!card.phone && !card.email && !card.name) {
    toast('No contact info found', 'err'); return;
  }
  saveContact(card);
});

function saveContact(c) {
  /* Try Web Contacts API (Android Chrome 80+) */
  if (navigator.contacts && navigator.contacts.select) {
    navigator.contacts.select(['name','tel','email'], { multiple: false })
      .then(() => toast('Contact picker opened!', 'ok'))
      .catch(() => downloadVCF(c));
  } else {
    /* Fallback: .vcf file download.
       On iOS and Android, opening the .vcf file triggers the native
       "Add to Contacts" flow automatically. */
    downloadVCF(c);
  }
}

function buildVCF(c) {
  let v = 'BEGIN:VCARD\nVERSION:3.0\n';
  if (c.name) {
    v += `FN:${c.name}\n`;
    const p = c.name.trim().split(' '), last = p.pop()||'', first = p.join(' ');
    v += `N:${last};${first};;;\n`;
  }
  if (c.title)       v += `TITLE:${c.title}\n`;
  if (c.company)     v += `ORG:${c.company}\n`;
  if (c.phone)       v += `TEL;TYPE=CELL:${c.phone}\n`;
  if (c.email)       v += `EMAIL:${c.email}\n`;
  if (c.website)     v += `URL:${c.website}\n`;
  if (c.address)     v += `ADR;TYPE=WORK:;;${c.address};;;;\n`;
  if (c.socialMedia) v += `X-SOCIALPROFILE:${c.socialMedia}\n`;
  if (c.notes)       v += `NOTE:${c.notes}\n`;
  return v + 'END:VCARD';
}

function downloadVCF(c) {
  const blob = new Blob([buildVCF(c)], { type: 'text/vcard;charset=utf-8' });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), {
    href: url,
    download: ((c.name || c.company || 'contact').replace(/\s+/g,'_')) + '.vcf'
  });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1500);
  toast('VCF downloaded — open to import contact', 'ok');
}

/* ════════════════════════════════════════════
   COPY
════════════════════════════════════════════ */
document.getElementById('btn-copy').addEventListener('click', () => {
  const txt = Object.values(readFields()).filter(Boolean).join('\n');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(() => toast('Copied!','ok')).catch(() => legacyCopy(txt));
  } else legacyCopy(txt);
});

function legacyCopy(txt) {
  const ta = Object.assign(document.createElement('textarea'), {
    value: txt, style: 'position:fixed;top:-9999px'
  });
  document.body.appendChild(ta);
  ta.focus(); ta.select(); ta.setSelectionRange(0,99999);
  try { document.execCommand('copy'); toast('Copied!','ok'); } catch(e){}
  document.body.removeChild(ta);
}

/* ════════════════════════════════════════════
   LOAD & RENDER CARDS
════════════════════════════════════════════ */
const SVG = {
  phone:`<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 01-2.18 2A19.79 19.79 0 013.09 5.18 2 2 0 015.09 3h3a2 2 0 012 1.72c.13.96.36 1.9.7 2.81a2 2 0 01-.45 2.11L9.09 10.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0122 16.92z"/></svg>`,
  email:`<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
  web:  `<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 010 20M12 2a15.3 15.3 0 000 20"/></svg>`,
  bldg: `<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`,
  pin:  `<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>`,
};

function ini(n){ return (n||'?').split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2)||'?'; }

async function loadCards() {
  try {
    const res = await fetch('/cards');
    cards = await res.json();
    renderCards();
  } catch(e){ console.error('loadCards',e); }
}

function renderCards() {
  const list  = document.getElementById('cards-list');
  const none  = document.getElementById('no-cards');
  const badge = document.getElementById('cnt-badge');
  if (!cards.length) {
    none.style.display='block'; list.innerHTML=''; badge.style.display='none'; return;
  }
  none.style.display='none'; badge.style.display='flex'; badge.textContent=cards.length;
  list.innerHTML = cards.map((c,i) => `
    <div class="ci">
      <div class="ci-top">
        <div class="ci-av">${ini(c.name||c.company)}</div>
        <div style="flex:1;min-width:0">
          <div class="ci-name">${he(c.name||c.company||'Unknown')}</div>
          ${c.title?`<div class="ci-sub">${he(c.title)}</div>`:''}
        </div>
        <span class="ci-type">${he(c.cardType||'Card')}</span>
      </div>
      <div class="ci-flds">
        ${c.phone            ?`<div class="ci-f">${SVG.phone}<span>${he(c.phone)}</span></div>`:''}
        ${c.email            ?`<div class="ci-f">${SVG.email}<span>${he(c.email)}</span></div>`:''}
        ${c.website          ?`<div class="ci-f">${SVG.web}<span>${he(c.website)}</span></div>`:''}
        ${c.company&&c.name  ?`<div class="ci-f">${SVG.bldg}<span>${he(c.company)}</span></div>`:''}
        ${c.address          ?`<div class="ci-f">${SVG.pin}<span>${he(c.address)}</span></div>`:''}
      </div>
      <div class="ci-acts">
        ${(c.phone||c.email||c.name)?`
        <button class="btn-s primary" onclick="cardContact(${i})" type="button">
          <svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
          Add to Contacts
        </button>`:''}
        <button class="btn-s" onclick="cardVCF(${i})" type="button">
          <svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
          .vcf
        </button>
        <button class="btn-s" onclick="cardCopy(${i})" type="button">
          <svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
          Copy
        </button>
        <button class="btn-s danger" onclick="cardDel('${c.id}')" type="button">
          <svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6M10 11v6M14 11v6M9 6V4h6v2"/></svg>
          Delete
        </button>
      </div>
    </div>`).join('');
}

function cardContact(i){ saveContact(cards[i]); }
function cardVCF(i)    { downloadVCF(cards[i]); }
function cardCopy(i)   {
  const c = cards[i];
  legacyCopy([c.name,c.title,c.company,c.phone,c.email,c.website,c.address,c.notes].filter(Boolean).join('\n'));
}
async function cardDel(id){
  try{
    await fetch('/cards/'+id, {method:'DELETE'});
    await loadCards();
    toast('Deleted');
  }catch(e){ toast('Delete failed','err'); }
}

/* ── Boot ── */
loadCards();
