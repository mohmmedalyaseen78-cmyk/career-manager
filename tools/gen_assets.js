// Generates ALL original visual assets for Career Manager (SVG sources, sprite atlases + JSON, backgrounds, CSS).
// Run: node tools/gen_assets.js   (needs `sharp`; no network, no fonts, no third-party artwork)
const fs = require('fs'), path = require('path');
const sharp = require('/opt/npm-tools/node_modules/sharp');
const ROOT = path.join(__dirname, '..', 'ui');
const VIS = path.join(ROOT, 'assets', 'visuals');
const SRC = path.join(VIS, 'src'), SPR = path.join(VIS, 'sprites');
for (const d of [SRC, SPR, path.join(ROOT, 'css')]) fs.mkdirSync(d, { recursive: true });

// ---- deterministic RNG
let seed = 7; const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
const reseed = s => { seed = s; };

const C = { bg: '#121416', s1: '#1B1F22', s2: '#24292C', s3: '#2C3236', line: '#343A3E', txt: '#F1EEE6', mut: '#8F918E',
  gold: '#C5A46D', gold2: '#D8BD8C', bur: '#762F3B', bur2: '#4B2029', ok: '#668A70', warn: '#D0A354', bad: '#B95A54',
  info: '#8297A0', pitch: '#243B31', pline: '#87998B' };

// ============ 1) UI line icons (24x24, stroke) — white in atlas; tinted at runtime with CSS mask ============
const S = (d, extra = '') => `<g fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</g>`;
const ICONS = {
  central: S('<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-6h4v6"/>'),
  squad: S('<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.6 2.7-6 6-6s6 2.4 6 6"/><circle cx="17.2" cy="9" r="2.4"/><path d="M16.5 14.2c2.6.3 4.5 2.3 4.5 5.3"/>'),
  transfers: S('<path d="M4 8h13"/><path d="M13.5 4.5 17 8l-3.5 3.5"/><path d="M20 16H7"/><path d="M10.5 12.5 7 16l3.5 3.5"/>'),
  office: S('<rect x="3.5" y="8" width="17" height="11.5" rx="1.8"/><path d="M9 8V6.2c0-.7.5-1.2 1.2-1.2h3.6c.7 0 1.2.5 1.2 1.2V8"/><path d="M3.5 13h17"/>'),
  competitions: S('<path d="M7.5 4h9v5.5a4.5 4.5 0 0 1-9 0z"/><path d="M7.5 6H4.5c0 3 1.2 4.4 3.3 4.7"/><path d="M16.5 6h3c0 3-1.2 4.4-3.3 4.7"/><path d="M12 14v3.5"/><path d="M8.5 20h7"/><path d="M9.5 17.5h5"/>'),
  calendar: S('<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/><path d="M8 14h2M14 14h2M8 17h2"/>'),
  news: S('<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M7 9h6M7 12.5h10M7 16h10"/><path d="M15.5 8.5h1.5"/>'),
  inbox: S('<path d="M4 6.5h16v11H4z"/><path d="m4.5 7 7.5 6 7.5-6"/>'),
  settings: S('<path d="M4 7h9M17 7h3M4 17h3M11 17h9M4 12h3M11 12h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/><circle cx="9" cy="12" r="0.1"/>'),
  save: S('<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><rect x="8" y="13" width="8" height="7"/>'),
  search: S('<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5"/>'),
  filter: S('<path d="M4 5.5h16l-6 7.2V19l-4-2v-4.3z"/>'),
  sort: S('<path d="M8 19V5M5 8l3-3 3 3M16 5v14M13 16l3 3 3-3"/>'),
  more: S('<circle cx="5.5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="18.5" cy="12" r="1"/>'),
  chevron_left: S('<path d="m14.5 5-7 7 7 7"/>'),
  chevron_right: S('<path d="m9.5 5 7 7-7 7"/>'),
  chevron_down: S('<path d="m5 9.5 7 7 7-7"/>'),
  close: S('<path d="M6 6l12 12M18 6 6 18"/>'),
  check: S('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
  plus: S('<path d="M12 5v14M5 12h14"/>'),
  play: S('<path d="M8 5.5v13l10.5-6.5z"/>'),
  pause: S('<path d="M8 5.5v13M16 5.5v13"/>'),
  next: S('<path d="M6 5.5v13l8.5-6.5zM18 5.5v13"/>'),
  star: S('<path d="m12 4 2.4 5 5.4.7-4 3.8 1 5.4-4.8-2.7-4.8 2.7 1-5.4-4-3.8 5.4-.7z"/>'),
  eye: S('<path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/><circle cx="12" cy="12" r="2.6"/>'),
  scout: S('<circle cx="10" cy="10" r="5.5"/><path d="m14 14 6 6"/><path d="M7.5 10h5M10 7.5v5"/>'),
  handshake: S('<path d="M3 11l4-3 4 1.5 3-1.5 4 3.2"/><path d="M3 11v5l4 3 3-1.5M21 11.2V16l-3.5 3-3-1.5"/><path d="m10 14.5 2.5 2M12.5 12.5l2.2 2"/>'),
  loan: S('<path d="M5 12a7 7 0 0 1 12-4.8L19 9"/><path d="M19 5v4h-4"/><path d="M19 12a7 7 0 0 1-12 4.8L5 15"/><path d="M5 19v-4h4"/>'),
  contract: S('<path d="M7 3.5h8l3.5 3.5v13.5H7z"/><path d="M15 3.5V7h3.5M10 12h5M10 15.5h5"/>'),
  money: S('<rect x="3" y="7" width="18" height="10" rx="1.8"/><circle cx="12" cy="12" r="2.4"/><path d="M6.5 10v4M17.5 10v4"/>'),
  flag: S('<path d="M6 21V4"/><path d="M6 5h11l-2.5 3.5L17 12H6"/>'),
  lock: S('<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>'),
  info: S('<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.2"/>'),
  warning: S('<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17v.2"/>'),
  back: S('<path d="M19 12H5M11 6l-6 6 6 6"/>'),
  photo: S('<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><circle cx="9" cy="10.5" r="1.6"/><path d="m4 17 5-4.5 4 3.5 3-2.5 4.5 4"/>'),
  exit: S('<path d="M10 4.5H5.5v15H10M14 8l4 4-4 4M18 12H9.5"/>'),
  folder: S('<path d="M3.5 7.5V18h17V9.5H11L9 7.5z"/>'),
  new_career: S('<circle cx="12" cy="12" r="8.5"/><path d="M12 8v8M8 12h8"/>'),
  continue: S('<circle cx="12" cy="12" r="8.5"/><path d="m10 8.5 5 3.5-5 3.5z"/>'),
  credits: S('<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.2"/>'),
};

// ============ 2) football events (colored, 32x32) ============
const EVENTS = {
  goal: `<circle cx="16" cy="16" r="12" fill="${C.txt}"/><path d="m16 10.5 4.2 3-1.6 5h-5.2l-1.6-5z" fill="#1B1F22"/><path d="M16 10.5V5M20.2 13.5l5-1.8M18.6 18.5l3.2 4.2M13.4 18.5l-3.2 4.2M11.8 13.5l-5-1.8" stroke="#1B1F22" stroke-width="1.6" fill="none"/>`,
  yellow_card: `<rect x="9" y="5" width="14" height="22" rx="2" fill="${C.warn}" transform="rotate(8 16 16)"/>`,
  red_card: `<rect x="9" y="5" width="14" height="22" rx="2" fill="${C.bad}" transform="rotate(8 16 16)"/>`,
  substitution: `<path d="M5 11h17M17 6l5 5-5 5" stroke="${C.ok}" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M27 21H10M15 16l-5 5 5 5" stroke="${C.bad}" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
  injury: `<rect x="4" y="4" width="24" height="24" rx="5" fill="${C.bad}"/><path d="M16 9v14M9 16h14" stroke="${C.txt}" stroke-width="3.4" stroke-linecap="round"/>`,
  assist: `<path d="M5 22c4-1 6-4 8-9 3 0 6 1 8 3l5 1c1.5.4 1.5 2.6 0 3l-11 3c-4 1-7 0-10-1z" fill="${C.gold}"/><path d="M13 13l2-5h4" stroke="${C.gold2}" stroke-width="2" fill="none" stroke-linecap="round"/>`,
  whistle: `<circle cx="11" cy="19" r="7.5" fill="${C.gold}"/><rect x="14" y="8" width="14" height="7" rx="3" fill="${C.gold2}"/><circle cx="11" cy="19" r="2.6" fill="${C.s1}"/>`,
  save_glove: `<path d="M9 28v-9L7 12c-.4-1.4 1.6-2 2.2-.8L11 14V6c0-1.6 2.4-1.6 2.4 0v7V5c0-1.6 2.4-1.6 2.4 0v8V6c0-1.6 2.4-1.6 2.4 0v8l1.2-3c.6-1.4 2.8-.6 2.4.9L21 21v7z" fill="${C.txt}"/>`,
  stopwatch: `<circle cx="16" cy="18" r="10" fill="none" stroke="${C.txt}" stroke-width="2.4"/><path d="M16 12v6l4 2.5M13 4h6M16 4v4" stroke="${C.gold}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`,
  penalty: `<rect x="4" y="9" width="24" height="16" rx="1" fill="none" stroke="${C.txt}" stroke-width="2.2"/><circle cx="16" cy="25" r="2.4" fill="${C.gold}"/><path d="M4 17h24" stroke="${C.line}" stroke-width="1.4"/>`,
  corner: `<path d="M8 28V5" stroke="${C.txt}" stroke-width="2.4" stroke-linecap="round"/><path d="M8 6l16 4.5L8 15z" fill="${C.gold}"/>`,
};

// ============ 3) status indicators (colored, 20x20) ============
const STATUS = {
  fit: `<circle cx="10" cy="10" r="8.5" fill="${C.ok}"/><path d="m6 10.3 2.7 2.7L14 7.5" stroke="${C.txt}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
  tired: `<circle cx="10" cy="10" r="8.5" fill="${C.warn}"/><path d="M6 12.5h8M6.5 9.5h7" stroke="#1B1F22" stroke-width="2" stroke-linecap="round"/>`,
  injured: `<circle cx="10" cy="10" r="8.5" fill="${C.bad}"/><path d="M10 5.8v8.4M5.8 10h8.4" stroke="${C.txt}" stroke-width="2.4" stroke-linecap="round"/>`,
  suspended: `<circle cx="10" cy="10" r="8.5" fill="${C.bad}"/><rect x="6.6" y="5.6" width="6.8" height="8.8" rx="1" fill="${C.txt}"/>`,
  morale_high: `<circle cx="10" cy="10" r="8.5" fill="${C.gold}"/><circle cx="7.2" cy="8.2" r="1.1" fill="#1B1F22"/><circle cx="12.8" cy="8.2" r="1.1" fill="#1B1F22"/><path d="M6.2 11.6c1.8 3 5.8 3 7.6 0" stroke="#1B1F22" stroke-width="1.6" fill="none" stroke-linecap="round"/>`,
  morale_mid: `<circle cx="10" cy="10" r="8.5" fill="${C.info}"/><circle cx="7.2" cy="8.2" r="1.1" fill="#1B1F22"/><circle cx="12.8" cy="8.2" r="1.1" fill="#1B1F22"/><path d="M6.6 13h6.8" stroke="#1B1F22" stroke-width="1.6" stroke-linecap="round"/>`,
  morale_low: `<circle cx="10" cy="10" r="8.5" fill="${C.bad}"/><circle cx="7.2" cy="8.2" r="1.1" fill="#1B1F22"/><circle cx="12.8" cy="8.2" r="1.1" fill="#1B1F22"/><path d="M6.2 14c1.8-3 5.8-3 7.6 0" stroke="#1B1F22" stroke-width="1.6" fill="none" stroke-linecap="round"/>`,
  form_up: `<path d="M10 3 17 12H3z" fill="${C.ok}"/><rect x="8" y="12" width="4" height="5" fill="${C.ok}"/>`,
  form_flat: `<path d="M3 7h14v2.6H3zM3 11.4h14V14H3z" fill="${C.info}"/>`,
  form_down: `<path d="M10 17 3 8h14z" fill="${C.bad}"/><rect x="8" y="3" width="4" height="5" fill="${C.bad}"/>`,
  new: `<circle cx="10" cy="10" r="8.5" fill="${C.gold}"/><path d="M10 5.5v9M5.5 10h9" stroke="#1B1F22" stroke-width="2.2" stroke-linecap="round"/>`,
  locked: `<circle cx="10" cy="10" r="8.5" fill="${C.s3}"/><rect x="6.2" y="9" width="7.6" height="5.6" rx="1" fill="${C.mut}"/><path d="M7.8 9V7.4a2.2 2.2 0 0 1 4.4 0V9" stroke="${C.mut}" stroke-width="1.6" fill="none"/>`,
};

// ============ 4) silhouettes (96x120). No faces, no real people. ============
const body = (shirt, num = '') => `<circle cx="48" cy="34" r="19" fill="#6a7075"/><path d="M8 120V92c0-17 14-27 40-27s40 10 40 27v28z" fill="#555b60"/><path d="M34 70q14 12 28 0l6 8q-20 14-40 0z" fill="${shirt}"/>`;
const SILS = {
  neutral: body('#7b8186'),
  gk: body(C.gold),
  df: body(C.info),
  mf: body(C.gold2 === '' ? C.txt : '#B0A88F'),
  fw: body(C.bad),
  manager: `<circle cx="48" cy="34" r="19" fill="#6a7075"/><path d="M6 120V94c0-18 15-28 42-28s42 10 42 28v26z" fill="#3a4045"/><path d="M48 66 34 80l14 40 14-40z" fill="#F1EEE6" opacity="0.9"/><path d="M44 80h8l3 8-7 24-7-24z" fill="${C.bur}"/><path d="M34 80 22 96M62 80l12 16" stroke="#2C3236" stroke-width="3"/>`,
};
const sizeOf = { neutral: [96, 120], gk: [96, 120], df: [96, 120], mf: [96, 120], fw: [96, 120], manager: [96, 120] };

// ============ 5) generic club badges (56x64) ============
const BADGE_COLORS = [[C.bur, C.gold], ['#2C3236', C.txt], [C.bad, C.txt], [C.gold, '#1B1F22'], ['#6B4E8A', C.txt], ['#C77A3B', '#1B1F22'],
  ['#3E6B73', C.txt], [C.txt, C.bur], ['#8C2F2F', C.gold2], ['#4A5560', C.gold], ['#A8884F', C.bur2], ['#5B3A2E', C.gold2]];
const badge = ([a, b], i) => {
  const shape = ['M28 3 52 10v22c0 14-10 24-24 29C14 56 4 46 4 32V10z', 'M5 5h46v26c0 16-10 25-23 29C15 56 5 47 5 31z', 'M28 3c10 5 18 6 24 6v22c0 14-9 24-24 30C13 55 4 45 4 31V9c6 0 14-1 24-6z'][i % 3];
  const dec = ['<path d="M4 28h48" stroke="B" stroke-width="7"/>', '<path d="M28 3v58" stroke="B" stroke-width="8"/>', '<path d="M4 18 52 40" stroke="B" stroke-width="7"/>', '<circle cx="28" cy="30" r="9" fill="B"/>'][i % 4].replace(/B/g, b);
  return `<defs><clipPath id="c${i}"><path d="${shape}"/></clipPath></defs><path d="${shape}" fill="${a}"/><g clip-path="url(#c${i})">${dec}</g><path d="${shape}" fill="none" stroke="#0e1012" stroke-width="2"/>`;
};
const BADGES = {}; BADGE_COLORS.forEach((c, i) => BADGES['badge_' + String(i + 1).padStart(2, '0')] = badge(c, i));

// ============ sprite packer ============
async function pack(name, defs, cell, extra = (x) => x, cols = 8) {
  const items = Object.entries(defs); const pad = 2;
  const w = Array.isArray(cell) ? cell[0] : cell, h = Array.isArray(cell) ? cell[1] : cell;
  const rows = Math.ceil(items.length / cols);
  const json = { image: `${name}.png`, image2x: `${name}@2x.png`, cell: { w, h, padding: pad }, sprites: {} };
  for (const scale of [1, 2]) {
    const comps = [];
    for (let i = 0; i < items.length; i++) {
      const [key, inner] = items[i]; const col = i % cols, row = Math.floor(i / cols);
      const vb = name === 'ui_icons' ? '0 0 24 24' : name === 'football_events' ? '0 0 32 32' : name === 'status_indicators' ? '0 0 20 20' : name === 'club_badges_generic' ? '0 0 56 64' : '0 0 96 120';
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb}" width="${w * scale}" height="${h * scale}">${inner}</svg>`;
      const buf = await sharp(Buffer.from(svg)).png().toBuffer();
      comps.push({ input: buf, left: (col * (w + 2 * pad) + pad) * scale, top: (row * (h + 2 * pad) + pad) * scale });
      if (scale === 1) json.sprites[key] = { x: col * (w + 2 * pad) + pad, y: row * (h + 2 * pad) + pad, w, h };
      fs.writeFileSync(path.join(SRC, `${name}.${key}.svg`), svg.replace(/width="\d+" height="\d+"/, `width="${w}" height="${h}"`));
    }
    const W = cols * (w + 2 * pad) * scale, H = rows * (h + 2 * pad) * scale;
    await sharp({ create: { width: W, height: H, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } }).composite(comps)
      .png({ compressionLevel: 9 }).toFile(path.join(SPR, scale === 1 ? `${name}.png` : `${name}@2x.png`));
    if (scale === 1) { json.size = { w: W, h: H }; }
  }
  fs.writeFileSync(path.join(SPR, `${name}.json`), JSON.stringify(json, null, 1));
  return json;
}

// ============ logo mark ============
const LOGO = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 72"><path d="M32 3 58 11v24c0 15-11 27-26 34C17 62 6 50 6 35V11z" fill="${C.bur2}" stroke="${C.gold}" stroke-width="3.2"/><path d="M12 36h40" stroke="${C.gold}" stroke-width="2.4"/><circle cx="32" cy="36" r="9" fill="none" stroke="${C.gold}" stroke-width="2.4"/><path d="M22 12h20v6H22zM22 60h20v-6H22z" fill="none" stroke="${C.gold2}" stroke-width="1.8"/><circle cx="32" cy="36" r="2.2" fill="${C.gold2}"/></svg>`;

// ============ backgrounds (original flat-vector illustrations, no gradients) ============
const W = 1366, H = 768;
const crowd = (x0, y0, x1, y1, step, colors) => { let o = ''; for (let y = y0; y < y1; y += step) for (let x = x0; x < x1; x += step) { const c = colors[Math.floor(rnd() * colors.length)]; o += `<rect x="${(x + rnd() * 2).toFixed(1)}" y="${(y + rnd() * 2).toFixed(1)}" width="${step * .55}" height="${step * .7}" rx="1" fill="${c}"/>`; } return o; };
const cone = (x, y, w, h, op = .05, col = C.txt) => `<polygon points="${x},${y} ${x - w / 2},${y + h} ${x + w / 2},${y + h}" fill="${col}" opacity="${op}"/>`;
const tower = (x, h) => `<rect x="${x - 4}" y="${h}" width="8" height="${400 - h}" fill="#0b0d0f"/><rect x="${x - 34}" y="${h - 30}" width="68" height="34" fill="#0b0d0f"/>` + [...Array(12)].map((_, i) => `<rect x="${x - 31 + (i % 6) * 11}" y="${h - 27 + Math.floor(i / 6) * 14}" width="8" height="10" fill="${C.txt}" opacity=".9"/>`).join('');
function bgMenu() { reseed(11); return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#0d0f11"/>
<polygon points="0,250 ${W},250 ${W},400 0,400" fill="#16191c"/>${crowd(0, 262, W, 392, 7, ['#23282c', '#2b3136', '#1d2125', '#32282b', '#3a3236'])}
<polygon points="0,400 ${W},400 ${W},440 0,440" fill="#101315"/>
${cone(180, 90, 520, 380, .045)}${cone(1190, 90, 520, 380, .045)}${tower(180, 70)}${tower(1190, 70)}
<polygon points="0,440 ${W},440 ${W},${H} 0,${H}" fill="#1a2620"/>
${[...Array(9)].map((_, i) => `<polygon points="${-300 + i * 230},${H} ${-300 + (i + 1) * 230},${H} ${(W / 2) + (-300 + (i + 1) * 230 - W / 2) * .35},440 ${(W / 2) + (-300 + i * 230 - W / 2) * .35},440" fill="${i % 2 ? '#1f2d26' : '#1a2620'}"/>`).join('')}
<ellipse cx="683" cy="600" rx="260" ry="62" fill="none" stroke="#3b4a41" stroke-width="3"/><path d="M130 ${H} 400 440M1236 ${H} 966 440" stroke="#3b4a41" stroke-width="3"/>
<rect width="${W}" height="${H}" fill="#0d0f11" opacity=".1"/></svg>`; }
function bgStands() { reseed(23); let o = ''; for (let r = 0; r < 14; r++) { const y = 150 + r * 40, h = 30 + r * 2; o += `<rect x="0" y="${y}" width="${W}" height="${h}" fill="${r % 2 ? '#181c1f' : '#1c2125'}"/>`; for (let x = 8; x < W; x += 34 + r) o += `<rect x="${x}" y="${y + 6}" width="${24 + r}" height="${h - 12}" rx="3" fill="${['#2a1c20', '#2c3236', '#3a2a2e', '#262b2f'][Math.floor(rnd() * 4)]}"/>`; }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#14171a"/><rect y="0" width="${W}" height="150" fill="#2a1d22"/><rect y="90" width="${W}" height="60" fill="#3a2830"/><rect y="40" width="${W}" height="50" fill="#33232a"/>${o}<rect width="${W}" height="${H}" fill="#0d0f11" opacity=".3"/></svg>`; }
function bgTunnel() { let o = ''; for (let i = 0; i < 12; i++) { const t = i / 12, pad = t * 560; o += `<rect x="${pad}" y="${pad * .62}" width="${W - 2 * pad}" height="${H - 1.24 * pad * .62 - pad * .1}" fill="${i % 2 ? '#121518' : '#171b1f'}"/>`; }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#0d0f11"/>${o}<rect x="560" y="345" width="246" height="150" fill="#d9d3c3"/><rect x="590" y="372" width="186" height="98" fill="#2c3b33"/><rect x="560" y="345" width="246" height="150" fill="none" stroke="#C5A46D" stroke-width="2" opacity=".5"/><polygon points="0,${H} ${W},${H} 806,495 560,495" fill="#101214"/><path d="M683 ${H}V495M300 ${H} 600 495M1066 ${H} 766 495" stroke="#242a2e" stroke-width="3"/><rect width="${W}" height="${H}" fill="#0d0f11" opacity=".3"/></svg>`; }
function bgFloods() { reseed(5); let o = ''; for (let k = 0; k < 3; k++) { const cx = 230 + k * 450; o += `<rect x="${cx - 120}" y="60" width="240" height="120" fill="#0b0d0f"/>`; for (let j = 0; j < 24; j++) o += `<rect x="${cx - 112 + (j % 8) * 28}" y="${70 + Math.floor(j / 8) * 36}" width="20" height="26" fill="${C.txt}" opacity=".92"/>`; o += cone(cx, 180, 560, 560, .06); }
  for (let i = 0; i < 26; i++) o += `<circle cx="${rnd() * W}" cy="${200 + rnd() * 400}" r="${40 + rnd() * 90}" fill="#F1EEE6" opacity="${.012 + rnd() * .02}"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#0b0d10"/>${o}<rect y="640" width="${W}" height="128" fill="#101412"/></svg>`; }
function bgPitchTex() { reseed(3); let o = ''; for (let i = 0; i < 16; i++) o += `<rect x="0" y="${i * 48}" width="512" height="48" fill="${i % 2 ? '#22372d' : '#26402f'}"/>`; for (let k = 0; k < 500; k++) o += `<rect x="${rnd() * 512}" y="${rnd() * 768}" width="1.5" height="${4 + rnd() * 7}" fill="${rnd() > .5 ? '#2c4a39' : '#1e3228'}" opacity=".55"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 768" width="512" height="768">${o}</svg>`; }
function pitchTop() { const w = 680, h = 960; let o = ''; for (let i = 0; i < 12; i++) o += `<rect x="0" y="${i * 80}" width="${w}" height="80" fill="${i % 2 ? '#223a2f' : '#264034'}"/>`;
  const L = (d) => `<path d="${d}" stroke="${C.pline}" stroke-width="3" fill="none"/>`;
  o += L(`M30 30H${w - 30}V${h - 30}H30z`) + L(`M30 ${h / 2}H${w - 30}`) + `<circle cx="${w / 2}" cy="${h / 2}" r="82" stroke="${C.pline}" stroke-width="3" fill="none"/><circle cx="${w / 2}" cy="${h / 2}" r="5" fill="${C.pline}"/>`
    + L(`M170 30V190H${w - 170}V30`) + L(`M250 30V90H${w - 250}V30`) + L(`M170 ${h - 30}V${h - 190}H${w - 170}V${h - 30}`) + L(`M250 ${h - 30}V${h - 90}H${w - 250}V${h - 30}`)
    + L(`M270 190a70 70 0 0 0 140 0`) + L(`M270 ${h - 190}a70 70 0 0 1 140 0`) + `<circle cx="${w / 2}" cy="140" r="4" fill="${C.pline}"/><circle cx="${w / 2}" cy="${h - 140}" r="4" fill="${C.pline}"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${o}</svg>`; }
function bgOffice() { return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#17191b"/><rect x="0" y="0" width="${W}" height="520" fill="#1d2023"/>${[...Array(7)].map((_, i) => `<rect x="${40 + i * 190}" y="20" width="150" height="460" fill="#1a1d20" stroke="#25292d" stroke-width="2"/>`).join('')}
<rect x="720" y="70" width="560" height="320" fill="#0f1215" stroke="#3a3f43" stroke-width="8"/>${[...Array(9)].map((_, i) => `<rect x="${740 + i * 58}" y="${390 - (60 + (i * 37) % 150)}" width="46" height="${60 + (i * 37) % 150}" fill="#1a1e22"/>`).join('')}<rect x="1000" y="70" width="6" height="320" fill="#3a3f43"/>
<rect x="0" y="520" width="${W}" height="248" fill="#241d1c"/><rect x="120" y="470" width="760" height="70" fill="#31282a"/><rect x="120" y="540" width="760" height="228" fill="#2a2224"/><rect x="170" y="430" width="120" height="40" fill="#3a3f43"/><rect x="190" y="400" width="80" height="30" fill="${C.gold}" opacity=".85"/><rect width="${W}" height="${H}" fill="#0d0f11" opacity=".35"/></svg>`; }
function bgTransfer() { reseed(9); let o = ''; for (let i = 0; i < 10; i++) { o += `<rect x="${i * 150 - 20}" y="40" width="130" height="330" fill="${i % 2 ? '#1a1d20' : '#1e2226'}"/>`; for (let k = 0; k < 6; k++) o += `<rect x="${i * 150 + 4}" y="${60 + k * 50}" width="82" height="${14 + (k * 7) % 12}" fill="#2b3035"/>`; }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><rect width="${W}" height="${H}" fill="#14171a"/>${o}<rect y="400" width="${W}" height="368" fill="#101315"/>${[...Array(8)].map((_, i) => `<path d="M${i * 190} ${H}L${683 + (i * 190 - 683) * .5} 400" stroke="#1d2226" stroke-width="3"/>`).join('')}${cone(300, 0, 500, 420, .035)}${cone(1000, 0, 500, 420, .035)}<rect width="${W}" height="${H}" fill="#0d0f11" opacity=".4"/></svg>`; }

(async () => {
  // sprites
  const sheets = {};
  sheets.ui_icons = await pack('ui_icons', ICONS, 24, null, 10);
  sheets.football_events = await pack('football_events', EVENTS, 32, null, 6);
  sheets.status_indicators = await pack('status_indicators', STATUS, 20, null, 6);
  sheets.player_silhouettes = await pack('player_silhouettes', SILS, [96, 120], null, 6);
  sheets.club_badges_generic = await pack('club_badges_generic', BADGES, [56, 64], null, 6);
  // logo + backgrounds
  fs.writeFileSync(path.join(VIS, 'logo_mark.svg'), LOGO);
  const bgs = { main_menu_stadium_night: bgMenu(), empty_stands_evening: bgStands(), stadium_tunnel: bgTunnel(), floodlights_atmosphere: bgFloods(), office_background: bgOffice(), transfer_background: bgTransfer() };
  for (const [k, svg] of Object.entries(bgs)) { fs.writeFileSync(path.join(SRC, k + '.svg'), svg); await sharp(Buffer.from(svg)).webp({ quality: 74 }).toFile(path.join(VIS, k + '.webp')); }
  fs.writeFileSync(path.join(SRC, 'pitch_texture.svg'), bgPitchTex()); await sharp(Buffer.from(bgPitchTex())).webp({ quality: 80 }).toFile(path.join(VIS, 'pitch_texture.webp'));
  fs.writeFileSync(path.join(VIS, 'pitch_top.svg'), pitchTop());
  // generated CSS for sprites (masks for tinted icons, backgrounds for colored sheets)
  let css = '/* GENERATED by tools/gen_assets.js - do not edit */\n';
  const cls = (sheet, prefix, mask) => {
    const j = sheets[sheet];
    css += `.${prefix}{display:inline-block;flex:none;width:${j.cell.w}px;height:${j.cell.h}px;` + (mask
      ? `background-color:currentColor;-webkit-mask:url(../assets/visuals/sprites/${sheet}.png) no-repeat;mask:url(../assets/visuals/sprites/${sheet}.png) no-repeat;}`
      : `background:url(../assets/visuals/sprites/${sheet}.png) no-repeat;}`) + '\n';
    css += `@media (min-resolution:1.5dppx){.${prefix}{` + (mask ? `-webkit-mask-image:url(../assets/visuals/sprites/${sheet}@2x.png);mask-image:url(../assets/visuals/sprites/${sheet}@2x.png);-webkit-mask-size:${j.size.w}px ${j.size.h}px;mask-size:${j.size.w}px ${j.size.h}px;` : `background-image:url(../assets/visuals/sprites/${sheet}@2x.png);background-size:${j.size.w}px ${j.size.h}px;`) + '}}\n';
    for (const [k, s] of Object.entries(j.sprites)) css += `.${prefix}-${k.replace(/_/g, '-')}{` + (mask ? `-webkit-mask-position:-${s.x}px -${s.y}px;mask-position:-${s.x}px -${s.y}px;` : `background-position:-${s.x}px -${s.y}px;`) + '}\n';
  };
  cls('ui_icons', 'ic', true); cls('football_events', 'ev', false); cls('status_indicators', 'st', false); cls('player_silhouettes', 'sil', false); cls('club_badges_generic', 'bdg', false);
  fs.writeFileSync(path.join(ROOT, 'css', 'sprites.css'), css);
  const sizes = fs.readdirSync(VIS).concat(fs.readdirSync(SPR).map(f => 'sprites/' + f)).filter(f => !fs.statSync(path.join(VIS, f)).isDirectory()).map(f => `${f}: ${(fs.statSync(path.join(VIS, f)).size / 1024).toFixed(0)} KB`);
  console.log(sizes.join('\n'));
})().catch(e => { console.error(e); process.exit(1); });
