(function(){
const D=window.DEMO,$=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const M=v=>v>=1e6?(v/1e6).toFixed(v>=1e7?0:1).replace('.0','')+' م':v>=1e3?Math.round(v/1e3)+' ألف':String(v);
const E=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const ic=n=>`<i class="ic ic-${n}"></i>`;
const TABS=[['central','الرئيسية','central'],['squad','الفريق','squad'],['transfers','الانتقالات','transfers'],['office','مكتب النادي','office'],['comps','البطولات','competitions'],['calendar','التقويم','calendar']];
const st={tab:'central',sub:{squad:'hub',transfers:'search'},selP:D.squad[0].id,selM:D.market[0].id,fSq:'ALL',qSq:'',sSq:'ovr',fMk:{pos:'ALL',age:99,ovr:0,q:''},pop:null};
const badge=(n,c='')=>`<i class="bdg bdg-badge-${String(n).padStart(2,'0')} ${c}"></i>`;
const sil=(g,c)=>`<i class="sil sil-${{GK:'gk',DF:'df',MF:'mf',FW:'fw'}[g]||'neutral'} ${c}"></i>`;
function toast(t){const e=$('#toast');e.textContent=t;e.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(()=>e.classList.remove('on'),2200)}
/* ---------- start ---------- */
const startItems=[['continue','continue','متابعة المسيرة',`${D.club.name} · ${D.season}`],['new','new-career','مسيرة جديدة',''],['load','folder','تحميل مسيرة','٢ محفوظة'],['settings','settings','الإعدادات',''],['credits','credits','الاعتمادات والمصادر',''],['exit','exit','خروج','']];
let sm=0;
function renderStart(){const m=$('#startMenu');m.innerHTML=startItems.map((x,i)=>`<button class="mi ${i===sm?'sel':''}" role="menuitem" data-i="${i}">${ic(x[1])}<span>${x[2]}</span><small>${x[3]}</small></button>`).join('');
$$('.mi',m).forEach(b=>{b.onclick=()=>{sm=+b.dataset.i;renderStart();pickStart(startItems[sm][0])};b.onmouseenter=()=>{};});}
function pickStart(k){if(k==='continue')go('game');else toast('هذه الشاشة ستُبنى بعد الموافقة على التصميم')}
/* ---------- shell ---------- */
function renderTop(){const c=D.club,m=D.manager,open=D.tasks.length;
$('#top').innerHTML=`<div class="who">${badge(c.badge,'badge')}<div><b>${E(c.name)}</b><span>${E(c.league)} · المركز <span class="num">${c.position}</span></span></div></div><div class="sep"></div>
<div class="mgr"><div class="av">${ic('photo')}</div><div><b>${E(m.name)}</b><span>مدرب · سمعة <span class="num">${m.reputation}</span></span></div></div><div class="sep"></div>
<div><b style="font-size:14px">${E(D.date)}</b><br><span class="muted" style="font-size:13px">موسم <span class="num">${D.season}</span></span></div>
<div class="sp"></div>
<div class="bud"><div>ميزانية الانتقالات<b>${M(c.transfer_budget)}</b></div><div>ميزانية الرواتب<b>${M(c.wage_budget)} أسبوعياً</b></div></div><div class="sep"></div>
<button class="tb" title="المهام" aria-label="المهام" data-act="tasks">${ic('inbox')}<span class="cnt num">${open}</span></button>
<button class="tb" title="الأخبار" aria-label="الأخبار" data-act="news">${ic('news')}</button>
<button class="tb" title="حفظ" aria-label="حفظ" data-act="save">${ic('save')}</button>
<button class="tb" title="الإعدادات" aria-label="الإعدادات" data-act="settings">${ic('settings')}</button>`;
$$('#top .tb').forEach(b=>b.onclick=()=>{const a=b.dataset.act;if(a==='save')toast('تم حفظ المسيرة');else if(a==='tasks')setTab('central');else toast('سيُبنى بعد الموافقة على التصميم')});
$('#nav').innerHTML=TABS.map((t,i)=>`<button class="tab ${st.tab===t[0]?'on':''}" role="tab" data-t="${t[0]}">${ic(t[2])}${t[1]}${t[0]==='transfers'&&D.tasks.some(x=>x.go==='transfers')?'<i class="dot"></i>':''}</button>`).join('');
$$('#nav .tab').forEach(b=>b.onclick=()=>setTab(b.dataset.t));}
function setTab(t){st.tab=t;st.pop=null;renderTop();renderBody()}
function go(s){$$('.screen').forEach(e=>e.classList.toggle('on',e.id===s));if(s==='game'){renderTop();renderBody()}}
function renderBody(){const b=$('#body');b.innerHTML='';const pg=document.createElement('div');pg.className='page on';b.appendChild(pg);
({central:central,squad:squad,transfers:transfers}[st.tab]||later)(pg);}
function later(pg){const n=TABS.find(t=>t[0]===st.tab);pg.innerHTML=`<div class="soon-box">${ic(n[2])}<b style="font-size:18px;color:var(--t2)">${n[1]}</b><span>يُبنى بعد الموافقة على تصميم الشاشات الأربع</span></div>`}
/* ---------- central ---------- */
function central(pg){const n=D.next_match,l=D.last_match,c=D.club,bd=D.board;
const lvl={good:['ok','جيدة'],very_good:['ok','ممتازة'],ok:['warn','مقبولة'],low:['warn','متراجعة'],bad:['bad','ضعيفة']}[bd.level]||['warn','مقبولة'];
const obj={avoid_relegation:'تجنّب الهبوط',mid_table:'الوصول إلى وسط الجدول',top_half:'إنهاء النصف الأعلى',european_spot:'التأهل لمسابقة أوروبية',title:'المنافسة على اللقب',promotion:'الصعود'}[bd.objective]||bd.objective;
const tIcon={injury:'warning',contract:'contract',offer:'handshake',job:'flag'};
pg.innerHTML=`<div class="grid-c">
<div class="hero"><div class="veil"></div><div class="in"><div class="lbl">المباراة القادمة · ${E(n.comp)} · الجولة <span class="num">${n.round}</span></div>
<div class="vs"><div class="t">${badge(1+((n.home_id)%12),'b72')}<b>${E(n.home)}</b><span>${n.home_id===c.id?'أنت':'المركز '+n.opp_pos}</span></div>
<div class="mid"><div class="big">ضد</div><span>${E(n.date)}</span><span>${n.venue}</span></div>
<div class="t">${badge(1+((n.away_id)%12),'b72')}<b>${E(n.away)}</b><span>${n.away_id===c.id?'أنت':'المركز '+n.opp_pos}</span></div></div>
<div class="act"><button class="btn pri" data-a="play">${ic('play')}ابدأ المباراة</button><button class="btn" data-a="prep">${ic('squad')}التشكيلة والخطة</button><button class="btn" data-a="sim">${ic('next')}محاكاة سريعة</button></div></div></div>
<div class="right-col">
 <div class="card"><div class="ch"><h3>مهامك</h3><span class="pill gold num">${D.tasks.length}</span></div><ul class="tasklist">${D.tasks.map(t=>`<li><button class="task p${t.prio}" data-go="${t.go}" data-pid="${t.pid||''}">${ic(tIcon[t.kind]||'info')}<span class="t">${E(t.text)}</span>${ic('chevron-left')}</button></li>`).join('')}</ul></div>
 <div class="card"><div class="ch"><h3>ثقة الإدارة</h3><span class="pill ${lvl[0]}">${lvl[1]}</span></div><div class="board"><div class="meter ${lvl[0]}"><i style="width:${bd.value}%"></i></div><div class="muted" style="font-size:13px">هدف الموسم: ${obj}${bd.target?` (المركز <span class="num">${bd.target}</span> أو أفضل)`:''}</div></div></div>
 <div class="card" style="flex:1;min-height:0;overflow:hidden"><div class="ch"><h3>آخر الأخبار</h3><button class="link" data-act="news">كل الأخبار ${ic('chevron-left')}</button></div>${D.news.slice(0,2).map(x=>`<div class="news-i"><b>${E(x.title)}</b><span>${E(x.line)}</span></div>`).join('')}</div>
</div>
<div class="left-col">
 <div class="card"><div class="ch"><h3>جدول الدوري</h3><button class="link" data-go="comps">الجدول الكامل ${ic('chevron-left')}</button></div>
  <table class="tbl mini"><thead><tr><th>#</th><th>النادي</th><th>لعب</th><th>فارق</th><th>نقاط</th></tr></thead><tbody>${D.table.map(r=>`<tr class="${r.me?'me':''}"><td class="num">${r.pos}</td><td>${E(r.club)}</td><td class="num">${r.p}</td><td class="num">${r.gd>0?'+':''}${r.gd}</td><td class="num"><b>${r.pts}</b></td></tr>`).join('')}</tbody></table></div>
 <div class="card"><div class="ch"><h3>آخر نتيجة</h3></div><div style="padding:6px 16px 16px;text-align:center"><div class="muted" style="font-size:13px">${E(l.date)} · الجولة <span class="num">${l.round}</span></div>
  <div style="display:flex;justify-content:center;align-items:center;gap:18px;margin-top:14px"><b style="font-size:15px;width:140px;text-align:left">${E(l.home)}</b><b class="num" style="font-size:34px;color:var(--gold-l)">${l.ag} - ${l.hg}</b><b style="font-size:15px;width:140px;text-align:right">${E(l.away)}</b></div></div></div>
</div></div>`;
$$('[data-go]',pg).forEach(b=>b.onclick=()=>{if(b.dataset.pid)st.selP=+b.dataset.pid;setTab(b.dataset.go)});
$$('[data-a]',pg).forEach(b=>b.onclick=()=>toast('المباراة التفاعلية ستُوصَل بعد الموافقة على التصميم'));
$$('[data-act=news]',pg).forEach(b=>b.onclick=()=>toast('شاشة الأخبار تُبنى بعد الموافقة'));}
/* ---------- shared ---------- */
const subs=(arr,cur,key)=>`<div class="sub" role="tablist">${arr.map(a=>`<button class="stab ${cur===a[0]?'on':''}" data-s="${a[0]}">${a[1]}${a[2]?'<span class="soon">قريباً</span>':''}</button>`).join('')}</div>`;
const statusIcons=p=>`<span class="sts">${p.injury_days>0?'<i class="st st-injured" title="مصاب"></i>':p.fitness<75?'<i class="st st-tired" title="متعب"></i>':'<i class="st st-fit" title="جاهز"></i>'}<i class="st st-morale-${p.morale>=70?'high':p.morale>=45?'mid':'low'}" title="المعنويات"></i><i class="st st-form-${p.form>=70?'up':p.form>=45?'flat':'down'}" title="الفورمة"></i></span>`;
const ovrC=v=>`<span class="ovr num ${v>=80?'h':''}">${v}</span>`;
const GRP=[['ALL','الكل'],['GK','حراس'],['DF','دفاع'],['MF','وسط'],['FW','هجوم']];
/* ---------- squad ---------- */
function squad(pg){const SUBS=[['hub','مركز الفريق'],['mgmt','إدارة الفريق',1],['tac','الخطط',1],['dev','التطوير',1],['train','التدريب',1]];
pg.innerHTML=subs(SUBS,st.sub.squad)+'<div class="split" id="sp"></div>';
$$('.stab',pg).forEach(b=>b.onclick=()=>{st.sub.squad=b.dataset.s;squad(pg)});
const sp=$('#sp',pg);
if(st.sub.squad!=='hub'){sp.style.display='block';sp.innerHTML=`<div class="soon-box">${ic('info')}<b style="font-size:17px;color:var(--t2)">${SUBS.find(s=>s[0]===st.sub.squad)[1]}</b><span>هذا القسم داخل «الفريق» وسيُبنى بعد الموافقة على التصميم</span></div>`;return}
let rows=D.squad.filter(p=>(st.fSq==='ALL'||p.grp===st.fSq)&&(!st.qSq||p.name.includes(st.qSq)));
rows.sort((a,b)=>st.sSq==='ovr'?b.ovr-a.ovr:st.sSq==='age'?a.age-b.age:st.sSq==='contract'?a.contract_left-b.contract_left:a.name.localeCompare(b.name,'ar'));
if(!rows.find(r=>r.id===st.selP)&&rows.length)st.selP=rows[0].id;
sp.innerHTML=`<div class="card" style="min-height:0"><div class="tools">${GRP.map(g=>`<button class="chip ${st.fSq===g[0]?'on':''}" data-g="${g[0]}">${g[1]}</button>`).join('')}<span class="sp" style="flex:1"></span>
<input class="inp" id="q" placeholder="بحث عن لاعب ( / )" value="${E(st.qSq)}" style="width:170px"><select class="inp" id="so"><option value="ovr">الترتيب: التقييم</option><option value="age">العمر</option><option value="contract">نهاية العقد</option><option value="name">الاسم</option></select></div>
<div class="scroll lt"><table class="tbl"><thead><tr><th>اللاعب</th><th>المركز</th><th>العمر</th><th>التقييم</th><th>الحالة</th><th>الدور</th><th>العقد</th></tr></thead><tbody>${rows.map(p=>`<tr class="row ${p.id===st.selP?'sel':''}" tabindex="0" data-id="${p.id}"><td><div class="pl">${sil(p.grp,'sil s28')}<b>${E(p.name)}</b></div></td><td class="pos">${p.pos_ar}</td><td class="num">${p.age}</td><td>${ovrC(p.ovr)}</td><td>${statusIcons(p)}</td><td class="sec">${p.role}</td><td class="sec">${p.contract_left?p.contract_left+' سنة':'<span style="color:var(--warn)">تنتهي هذا الموسم</span>'}</td></tr>`).join('')}</tbody></table></div></div><div class="card det" id="det"></div>`;
$('#so',pg).value=st.sSq;
$$('.chip',pg).forEach(b=>b.onclick=()=>{st.fSq=b.dataset.g;squad(pg)});
$('#so',pg).onchange=e=>{st.sSq=e.target.value;squad(pg)};
$('#q',pg).oninput=e=>{st.qSq=e.target.value;const pos=e.target.selectionStart;squad(pg);const q=$('#q',pg);q.focus();q.setSelectionRange(pos,pos)};
$$('.row',pg).forEach(r=>{r.onclick=()=>{st.selP=+r.dataset.id;squad(pg)};r.onkeydown=ev=>navRows(ev,r,pg,()=>squad(pg),'selP')});
detail(pg);}
function navRows(ev,r,pg,re,key){const rs=$$('.row',r.closest('table'));const i=rs.indexOf(r);let n=null;if(ev.key==='ArrowDown')n=rs[i+1];if(ev.key==='ArrowUp')n=rs[i-1];if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();r.click();return}
if(n){ev.preventDefault();st[key]=+n.dataset.id;re();const nr=$(`.row[data-id="${n.dataset.id}"]`,pg);nr&&nr.focus()}}
function detail(pg){const p=D.squad.find(x=>x.id===st.selP);if(!p)return;const f=p.face,keys=p.grp==='GK'?[['DIV','غطس'],['HAN','تعامل'],['KIC','ركل'],['REF','ردة فعل'],['SPD','سرعة'],['POS','تمركز']]:[['PAC','سرعة'],['SHO','تسديد'],['PAS','تمرير'],['DRI','مراوغة'],['DEF','دفاع'],['PHY','بدنية']];
$('#det',pg).innerHTML=`<div class="hd">${sil(p.grp,'sil s64')}<div><h2>${E(p.name)}</h2><div class="muted">${p.pos_ar} · <span class="num">${p.age}</span> سنة · ${p.nat}</div></div><div class="ovrbig"><b class="num">${p.ovr}</b><span>التقييم</span></div></div>
<div class="faces">${keys.map(k=>`<div><b class="num">${f[k[0]]??'—'}</b><span>${k[1]}</span></div>`).join('')}</div>
<div class="kv"><div><span>الإمكانات</span><b class="num">${p.pot}</b></div><div><span>القدم المفضلة</span>${p.foot}</div><div><span>الراتب الأسبوعي</span><b>${M(p.wage)}</b></div><div><span>القيمة التقديرية</span><b>${M(p.value)}</b></div><div><span>الطول / الوزن</span><span class="num" style="font-size:13px;color:var(--t1)">${p.height||'—'} / ${p.weight||'—'}</span></div><div><span>نمو اللاعب</span>${p.growth}</div></div>
<div class="note">المصدر: ${p.quality} — ليست تقييمات رسمية</div>
<div class="acts"><button class="btn sm pri" data-x="contract">${ic('contract')}تجديد العقد</button><button class="btn sm" data-x="more" id="mb">${ic('more')}المزيد</button></div>`;
$('#mb',pg).onclick=e=>{const old=$('.menu-pop',pg);if(old){old.remove();return}const r=e.currentTarget.getBoundingClientRect();const m=document.createElement('div');m.className='menu-pop';m.style.top=(r.top-150)+'px';m.style.left=r.left+'px';
m.innerHTML=[['transfers','handshake','عرضه للبيع'],['loan','إعارة'],['star','إضافة للقائمة المختصرة'],['lock','تغيير الدور (قريباً)',1]].map(a=>`<button ${a[3]||a[2]==='تغيير الدور (قريباً)'?'disabled':''} data-m="${a[0]}">${ic(a[1]==='إعارة'?'loan':a[1])}${a[2]}</button>`).join('');
document.body.appendChild(m);$$('button',m).forEach(b=>b.onclick=()=>{m.remove();toast('تم تنفيذ الإجراء (عرض تصميم)')})};
$('[data-x=contract]',pg).onclick=()=>toast('نافذة التفاوض على العقد تُبنى بعد الموافقة')}
/* ---------- transfers ---------- */
function confBars(c){const n=Math.max(1,Math.round(c*5));return `<span class="conf" title="مستوى الثقة بالتقدير">${[1,2,3,4,5].map(i=>`<i class="${i<=n?'f':''}"></i>`).join('')}</span>`}
function transfers(pg){const SUBS=[['search','البحث'],['short','القائمة المختصرة'],['scout','الكشّافون',1],['offers','العروض والمفاوضات'],['loans','الإعارات',1],['contracts','العقود',1]];
pg.innerHTML=subs(SUBS,st.sub.transfers)+'<div class="split" id="sp"></div>';
$$('.stab',pg).forEach(b=>b.onclick=()=>{st.sub.transfers=b.dataset.s;st.pop=null;transfers(pg)});
const sp=$('#sp',pg);
if(st.sub.transfers==='offers'){sp.style.display='block';const n=D.negotiation;sp.innerHTML=`<div class="card" style="padding:20px;max-width:760px"><h3 style="padding:0 0 12px">مفاوضة جارية</h3><div style="display:flex;align-items:center;gap:16px"><b style="font-size:17px">${E(n.player)}</b><span class="pill warn">بانتظار رد النادي</span></div><p class="muted" style="margin-top:10px">المرحلة الحالية في المحرك: <b class="sec">${E(n.stage)}</b> — لا تُعرض الحدود المخفية للنادي البائع، تظهر فقط ردوده وتقدير السوق.</p></div>`;return}
if(st.sub.transfers!=='search'){sp.style.display='block';sp.innerHTML=`<div class="soon-box">${ic('info')}<b style="font-size:17px;color:var(--t2)">${SUBS.find(s=>s[0]===st.sub.transfers)[1]}</b><span>يُبنى بعد الموافقة على التصميم</span></div>`;return}
const f=st.fMk;let rows=D.market.filter(p=>(f.pos==='ALL'||({GK:['GK'],DF:['CB','LB','RB'],MF:['CDM','CM','CAM','LM','RM'],FW:['LW','RW','ST']}[f.pos]||[]).includes(p.pos))&&p.age<=f.age&&p.ovr>=f.ovr&&(!f.q||p.name.includes(f.q)));
if(!rows.find(r=>r.id===st.selM)&&rows.length)st.selM=rows[0].id;
sp.innerHTML=`<div class="card" style="min-height:0;position:relative"><div class="tools">${GRP.map(g=>`<button class="chip ${f.pos===g[0]?'on':''}" data-g="${g[0]}">${g[1]}</button>`).join('')}<button class="btn sm ghost" id="fb">${ic('filter')}تصفية</button><span style="flex:1"></span><input class="inp" id="q" placeholder="بحث عن لاعب ( / )" value="${E(f.q)}" style="width:170px"></div>
<div class="scroll lt"><table class="tbl"><thead><tr><th>اللاعب</th><th>النادي</th><th>المركز</th><th>العمر</th><th>التقييم</th><th>القيمة التقديرية</th><th>العقد</th></tr></thead><tbody>${rows.map(p=>`<tr class="row ${p.id===st.selM?'sel':''}" tabindex="0" data-id="${p.id}"><td><b>${E(p.name)}</b></td><td class="sec">${E(p.club)}</td><td class="pos">${p.pos_ar}</td><td class="num">${p.age}</td><td>${ovrC(p.ovr)}</td><td><div class="rng"><b>${M(p.value_low)} – ${M(p.value_high)}</b></div></td><td class="sec">${p.contract_left} سنة</td></tr>`).join('')}</tbody></table></div>
${st.pop?`<div class="pop"><h4>تصفية البحث</h4><div class="fr"><label>أقصى عمر</label><input class="inp num" id="fa" type="number" min="16" max="45" value="${f.age===99?45:f.age}"></div><div class="fr"><label>أدنى تقييم</label><input class="inp num" id="fo" type="number" min="0" max="99" value="${f.ovr}"></div><div style="display:flex;gap:8px;margin-top:12px"><button class="btn sm pri" id="fok">تطبيق</button><button class="btn sm" id="fr">إعادة ضبط</button></div></div>`:''}</div><div class="card det" id="det"></div>`;
$$('.chip',pg).forEach(b=>b.onclick=()=>{f.pos=b.dataset.g;transfers(pg)});
$('#fb',pg).onclick=()=>{st.pop=!st.pop;transfers(pg)};
$('#q',pg).oninput=e=>{f.q=e.target.value;const pos=e.target.selectionStart;transfers(pg);const q=$('#q',pg);q.focus();q.setSelectionRange(pos,pos)};
if(st.pop){$('#fok',pg).onclick=()=>{f.age=+$('#fa',pg).value;f.ovr=+$('#fo',pg).value;st.pop=false;transfers(pg)};$('#fr',pg).onclick=()=>{f.age=99;f.ovr=0;st.pop=false;transfers(pg)}}
$$('.row',pg).forEach(r=>{r.onclick=()=>{st.selM=+r.dataset.id;transfers(pg)};r.onkeydown=ev=>navRows(ev,r,pg,()=>transfers(pg),'selM')});
const p=D.market.find(x=>x.id===st.selM);const dt=$('#det',pg);
if(!p){dt.innerHTML='<div class="soon-box"><span>لا توجد نتائج مطابقة</span></div>';return}
dt.innerHTML=`<div class="hd">${sil({GK:'GK',CB:'DF',LB:'DF',RB:'DF'}[p.pos]||(['CDM','CM','CAM','LM','RM'].includes(p.pos)?'MF':'FW'),'sil s64')}<div><h2>${E(p.name)}</h2><div class="muted">${p.pos_ar} · <span class="num">${p.age}</span> سنة</div><div class="muted">${E(p.club)}</div></div><div class="ovrbig"><b class="num">${p.ovr}</b><span>التقييم</span></div></div>
<div class="kv"><div style="grid-column:1/3"><span>القيمة التقديرية للسوق</span><b style="font-size:16px">${M(p.value_low)} – ${M(p.value_high)}</b>${confBars(p.confidence)}<div class="muted" style="font-size:13px">النطاق أوسع كلما قلّت معلوماتك. السعر الفعلي يُعرف بالتفاوض.</div></div><div><span>الراتب الحالي</span><b>${M(p.wage)} أسبوعياً</b></div><div><span>العقد</span><b>${p.contract_left} سنة</b></div></div>
<div class="note">المصدر: ${p.quality} — تقدير داخلي وليس تقييماً رسمياً</div>
<div class="acts"><button class="btn sm pri" id="neg">${ic('handshake')}بدء مفاوضة</button><button class="btn sm" id="sl">${ic('star')}للقائمة المختصرة</button><button class="btn sm" id="sc" disabled title="لا يوجد كشّافون بعد">${ic('scout')}إرسال كشّاف</button></div>`;
$('#neg',pg).onclick=()=>toast('نافذة المفاوضة (استفسار ← عرض النادي ← العقد) تُبنى بعد الموافقة');
$('#sl',pg).onclick=()=>toast('أُضيف إلى القائمة المختصرة (عرض تصميم)')}
/* ---------- states page ---------- */
function statesPage(){go('game');$('#top').innerHTML='<div class="who"><div><b>حالات العناصر</b><span>Career Manager · صفحة مرجعية للتصميم</span></div></div>';$('#nav').style.display='none';
const cell=(t,h)=>`<div class="card cell"><h5>${t}</h5>${h}</div>`;
const B=(c,t,x='')=>`<button class="btn ${c}" ${x}>${t}</button>`;
$('#body').innerHTML=`<div class="page on scroll"><div class="sg">
${cell('زر رئيسي — عادي',B('pri','متابعة'))}${cell('زر رئيسي — تمرير',B('pri fake-hover','متابعة'))}${cell('زر رئيسي — تركيز لوحة المفاتيح',B('pri fake-focus','متابعة'))}${cell('زر رئيسي — ضغط',B('pri fake-press','متابعة'))}${cell('زر رئيسي — معطّل',B('pri','متابعة','disabled'))}
${cell('زر ثانوي — عادي',B('','تفاصيل'))}${cell('زر ثانوي — تمرير',B('fake-hover','تفاصيل'))}${cell('زر ثانوي — تركيز',B('fake-focus','تفاصيل'))}${cell('زر ثانوي — ضغط',B('fake-press','تفاصيل'))}${cell('زر ثانوي — معطّل',B('','تفاصيل','disabled'))}
${cell('تبويب — عادي',`<button class="tab">${ic('squad')}الفريق</button>`)}${cell('تبويب — تمرير',`<button class="tab fake-hover">${ic('squad')}الفريق</button>`)}${cell('تبويب — محدد',`<button class="tab on">${ic('squad')}الفريق</button>`)}${cell('تبويب — تركيز',`<button class="tab fake-focus">${ic('squad')}الفريق</button>`)}${cell('تبويب فرعي — قريباً',`<button class="stab">التدريب<span class="soon">قريباً</span></button>`)}
${cell('شريحة تصفية — عادية',`<button class="chip">دفاع</button>`)}${cell('شريحة — تمرير',`<button class="chip fake-hover">دفاع</button>`)}${cell('شريحة — محددة',`<button class="chip on">دفاع</button>`)}${cell('حقل بحث — عادي',`<input class="inp" placeholder="بحث">`)}${cell('حقل — تركيز',`<input class="inp fake-focus" value="كريم">`)}
${cell('صف جدول — عادي',`<table class="tbl"><tr class="row"><td>لاعب</td><td>${ovrC(74)}</td></tr></table>`)}${cell('صف — تمرير',`<table class="tbl"><tr class="row"><td class="fake-hover" style="background:var(--s2)">لاعب</td><td>${ovrC(74)}</td></tr></table>`)}${cell('صف — محدد',`<table class="tbl"><tr class="row sel"><td>لاعب</td><td>${ovrC(74)}</td></tr></table>`)}${cell('صف ناديك',`<table class="tbl"><tr class="me"><td>نادي تجريبي 1</td><td>12</td></tr></table>`)}${cell('عنصر قائمة البداية — محدد',`<button class="mi sel" style="width:200px">${ic('continue')}متابعة</button>`)}
${cell('نجاح',`<span class="pill ok">${ic('check')}تم الحفظ</span>`)}${cell('تحذير',`<span class="pill warn">${ic('warning')}عقده ينتهي</span>`)}${cell('خطأ',`<span class="pill bad">${ic('warning')}العرض مرفوض</span>`)}${cell('معلومة',`<span class="pill">${ic('info')}تقدير داخلي</span>`)}${cell('تحميل',`<span class="sec">جارٍ التحميل…</span><div class="meter" style="width:140px"><i style="width:45%"></i></div>`)}
${cell('حالة اللاعب',`<span class="sts"><i class="st st-fit"></i><i class="st st-tired"></i><i class="st st-injured"></i><i class="st st-suspended"></i></span>`)}${cell('المعنويات والفورمة',`<span class="sts"><i class="st st-morale-high"></i><i class="st st-morale-mid"></i><i class="st st-morale-low"></i><i class="st st-form-up"></i><i class="st st-form-flat"></i><i class="st st-form-down"></i></span>`)}${cell('أحداث المباراة',`<span class="sts"><i class="ev ev-goal" style="zoom:.6"></i><i class="ev ev-yellow-card" style="zoom:.6"></i><i class="ev ev-red-card" style="zoom:.6"></i><i class="ev ev-substitution" style="zoom:.6"></i><i class="ev ev-injury" style="zoom:.6"></i></span>`)}${cell('ثقة الإدارة',`<div class="meter ok" style="width:160px"><i style="width:70%"></i></div><div class="meter warn" style="width:160px"><i style="width:40%"></i></div><div class="meter bad" style="width:160px"><i style="width:15%"></i></div>`)}${cell('نص مساعد / معطّل',`<span class="muted">نص ثانوي</span><span style="color:var(--t4)">نص معطّل</span>`)}
</div></div>`;}
/* ---------- keys ---------- */
document.addEventListener('keydown',e=>{const tag=(e.target.tagName||'');
if($('#start').classList.contains('on')){if(e.key==='ArrowDown'){sm=(sm+1)%startItems.length;renderStart();$$('.mi')[sm].focus();e.preventDefault()}if(e.key==='ArrowUp'){sm=(sm+startItems.length-1)%startItems.length;renderStart();$$('.mi')[sm].focus();e.preventDefault()}return}
if(tag==='INPUT'||tag==='SELECT'){if(e.key==='Escape')e.target.blur();return}
if(/^[1-6]$/.test(e.key)&&$('#game').classList.contains('on'))setTab(TABS[+e.key-1][0]);
if(e.key==='/'){const q=$('#q');if(q){e.preventDefault();q.focus()}}
if(e.key==='Escape'){const m=$('.menu-pop');if(m)m.remove();else if(st.pop){st.pop=false;renderBody()}}});
document.addEventListener('click',e=>{const m=$('.menu-pop');if(m&&!m.contains(e.target)&&!e.target.closest('#mb'))m.remove()});
renderStart();
const h=location.hash.slice(1);
if(h==='states'&&/[?&]dev=1/.test(location.search))statesPage();else if(TABS.some(t=>t[0]===h)){st.tab=h;go('game')}else go('start');
window.__cm={go,setTab,st};
$('#start').classList.contains('on')||0;
})();
