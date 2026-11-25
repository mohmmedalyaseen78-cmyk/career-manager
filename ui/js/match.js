/* Live match screen: pause/resume, speed, substitutions, tactics, formation; same engine as quick/instant. */
(()=>{const {S,$,$$,E,M,ic,POS,api,toast,modal,closeModal,go}=CM;
const EVT={goal:['goal','هدف'],pen_goal:['penalty','هدف من ركلة جزاء'],pen_miss:['penalty','ركلة جزاء ضائعة'],yc:['yellow-card','بطاقة صفراء'],rc:['red-card','بطاقة حمراء'],sub:['substitution','تبديل'],injury:['injury','إصابة'],save:['save-glove','تصدٍّ'],corner:['corner','ركنية']};
let st=null,feed=[],timer=null,speed=1,subOut=null,tab='sub';
async function startMatch(){const r=await api('match/start');if(r.error)return;st=r;feed=[];speed=1;subOut=null;tab='sub';go('match');draw(true)}
function evLine(e){const t=EVT[e.type]||['whistle',e.type];const mine=(e.side===st.side);const nm=e.name?E(e.name):'';const n2=e.name2?(e.type==='sub'?` ← ${E(e.name2)}`:` (صناعة ${E(e.name2)})`):'';
return `<div class="evr ${mine?'me':''}"><span class="mm num">${e.minute}'</span><i class="ev ev-${t[0]}" style="zoom:.6"></i><span>${t[1]} ${nm}${n2}</span></div>`}
function draw(full){const m=st,me=m.sides[m.side],op=m.sides[1-m.side];const H=m.sides[0],A=m.sides[1];
const el=$('#match');
if(full||!el.dataset.ready){el.dataset.ready=1;el.innerHTML=`<div class="mh" style="position:relative"><div class="mn num" id="mn"></div><div class="tm" id="hn"></div><div class="sc num" id="sc"></div><div class="tm" id="an"></div></div>
<div class="mbody"><div class="card" style="display:flex;flex-direction:column;min-height:0"><div class="ch"><h3>أحداث المباراة</h3></div><div class="feed" id="feed" style="flex:1"></div></div>
<div class="card" style="display:flex;flex-direction:column;min-height:0"><div class="sub" style="margin:0 10px"><button class="stab" data-t="sub">التبديلات</button><button class="stab" data-t="tac">الخطة</button><button class="stab" data-t="stat">الإحصاءات</button></div><div id="mp" class="scroll" style="flex:1;padding:6px"></div></div>
<div class="card" style="display:flex;flex-direction:column;min-height:0"><div class="ch"><h3>الفريق على أرض الملعب</h3></div><div class="scroll" id="onp" style="flex:1"></div></div></div>
<div class="mctl" id="ctl"></div>`;
$$('.stab',el).forEach(b=>b.onclick=()=>{tab=b.dataset.t;panel()})}
$('#hn').textContent=H.club;$('#an').textContent=A.club;$('#sc').textContent=`${m.score[1]} - ${m.score[0]}`;
$('#mn').textContent=m.finished?'انتهت المباراة':m.half?'استراحة الشوط':`الدقيقة ${m.minute}`;
$('#feed').innerHTML=feed.slice().reverse().map(evLine).join('')||'<div class="muted" style="padding:14px">لم تبدأ الأحداث بعد.</div>';
$$('.stab',el).forEach(b=>b.classList.toggle('on',b.dataset.t===tab));
$('#onp').innerHTML=me.on.map(p=>`<div class="pl-row"><span class="pos" style="width:70px">${POS[p.pos]||p.pos}</span><b>${E(p.name)}</b><span class="sp"></span>${CM.ovrC(p.ovr)}</div>`).join('');
panel();ctl()}
function panel(){const m=st,me=m.sides[m.side],op=m.sides[1-m.side],p=$('#mp');
$$('#match .stab').forEach(b=>b.classList.toggle('on',b.dataset.t===tab));
if(tab==='stat'){const a=m.sides[0].stats,b=m.sides[1].stats;const row=(l,k,f=x=>x)=>`<div class="stat"><b class="num">${f(b[k])}</b><span>${l}</span><b class="num">${f(a[k])}</b></div>`;
p.innerHTML=row('التسديدات','shots')+row('على المرمى','on_target')+row('الأهداف المتوقعة','xg')+row('الركنيات','corners')+row('الأخطاء','fouls')+row('البطاقات الصفراء','yc')+row('التصديات','saves')}
else if(tab==='tac'){const t=me.tactics;p.innerHTML=`<div class="fld"><label>التشكيل</label><select class="inp" id="mf">${m.formations.map(f=>`<option>${f}</option>`).join('')}</select></div><div class="fld"><label>العقلية</label><select class="inp" id="mt"><option value="defensive">دفاعية</option><option value="balanced">متوازنة</option><option value="attacking">هجومية</option></select></div><div class="fld"><label>الضغط</label><div class="sl"><input type="range" id="mpr" min="0" max="100" value="${t.pressing}"><span class="num">${t.pressing}</span></div></div><div class="fld"><label>الإيقاع</label><div class="sl"><input type="range" id="mtp" min="0" max="100" value="${t.tempo}"><span class="num">${t.tempo}</span></div></div>`;
$('#mt').value=t.mentality;const act=async b=>{pause();const r=await api('match/act',Object.assign({act:'tactics',from:st.n_events},b));if(!r.error){merge(r);draw()}};
$('#mt').onchange=e=>act({mentality:e.target.value});$('#mpr').onchange=e=>act({pressing:+e.target.value});$('#mtp').onchange=e=>act({tempo:+e.target.value});
$('#mf').onchange=async e=>{pause();const r=await api('match/act',{act:'formation',formation:e.target.value,from:st.n_events});if(!r.error){merge(r);toast(r.result==='ok'?'تم تغيير التشكيل':'لا يمكن تغيير التشكيل الآن',r.result!=='ok');draw()}}}
else{const left=m.max_subs-me.subs;p.innerHTML=`<div class="muted" style="padding:6px 10px">التبديلات المتبقية: <b class="num">${left}</b> — اختر لاعباً من الملعب ثم بديله من الاحتياط</div><div class="cols" style="gap:6px"><div>${me.on.map(x=>`<div class="pl-row ${subOut===x.id?'sel':''}" data-o="${x.id}"><span class="pos" style="width:46px">${x.pos}</span><span>${E(x.name)}</span><span class="sp"></span><span class="muted num">${x.fit}%</span></div>`).join('')}</div><div>${me.bench.map(x=>`<div class="pl-row" data-i="${x.id}"><span class="pos" style="width:46px">${x.pos}</span><span>${E(x.name)}</span><span class="sp"></span>${CM.ovrC(x.ovr)}</div>`).join('')}</div></div>${me.vacant?'<div class="msg warn">مركز شاغر بعد إصابة — اختر بديلاً من الاحتياط لملئه.</div>':''}`;
$$('[data-o]',p).forEach(r=>r.onclick=()=>{subOut=+r.dataset.o;panel()});
$$('[data-i]',p).forEach(r=>r.onclick=async()=>{if(me.vacant&&!subOut){const q=await api('match/act',{act:'fill',in:+r.dataset.i,from:st.n_events});if(!q.error){merge(q);draw()}return}
if(!subOut){toast('اختر اللاعب الذي سيخرج أولاً',true);return}pause();const q=await api('match/act',{act:'sub',out:subOut,in:+r.dataset.i,from:st.n_events});if(q.error)return;if(q.result!=='ok'){toast({no_substitutions_left:'استنفدت التبديلات',goalkeeper_swap_needs_goalkeeper:'حارس المرمى لا يُبدَّل إلا بحارس',in_player_unavailable:'اللاعب غير متاح'}[q.result]||'تعذّر التبديل',true)}else subOut=null;merge(q);draw()})}}
function merge(r){const keep=feed;st=r;feed=keep.concat(r.events||[]);}
function ctl(){const m=st,c=$('#ctl');
if(m.finished){c.innerHTML=`<button class="btn pri" id="fin">${ic('check')}إنهاء المباراة وعرض التقرير</button>`;$('#fin').onclick=finish;return}
c.innerHTML=`<button class="btn pri" id="pp">${timer?ic('pause')+'إيقاف مؤقت':ic('play')+'تشغيل'}</button><button class="btn" id="e1">حتى الحدث التالي</button><button class="btn" id="m5">+5 دقائق</button><button class="btn" id="hf">${m.minute<45?'حتى الاستراحة':'حتى النهاية'}</button><button class="btn" id="en">${ic('next')}إنهاء فوري</button><span style="flex:1"></span><label class="muted">السرعة</label><select class="inp" id="sp">${[['1','عادية'],['2','سريعة'],['4','أسرع']].map(([v,t])=>`<option value="${v}" ${+v===speed?'selected':''}>${t}</option>`).join('')}</select>`;
$('#pp').onclick=()=>timer?pause():play();$('#e1').onclick=()=>step({mode:'event'});$('#m5').onclick=()=>step({mode:'min',minutes:5});$('#hf').onclick=()=>step({mode:'half'});$('#en').onclick=()=>{pause();step({mode:'end'})};$('#sp').onchange=e=>{speed=+e.target.value;if(timer){pause();play()}}}
async function step(b){pause();const r=await api('match/advance',Object.assign({from:st.n_events},b));if(r.error)return;merge(r);draw()}
function play(){if(timer)return;const tick=async()=>{if(!timer)return;const r=await api('match/advance',{mode:'min',minutes:1,from:st.n_events});if(r.error||!timer){pause();return}merge(r);draw();if(st.finished||st.half&&st.minute===45&&false){pause();return}
const goalish=(r.events||[]).some(e=>['goal','pen_goal','rc','injury'].includes(e.type));if(st.minute===45&&st.half){pause();toast('استراحة الشوط — يمكنك التبديل وتغيير الخطة');return}
timer=setTimeout(tick,(goalish?1500:600)/speed)};timer=setTimeout(tick,50);ctl()}
function pause(){if(timer){clearTimeout(timer);timer=null;ctl()}}
async function finish(){const r=await api('match/commit');if(r.error)return;S.home=r.home;const rp=r.report;go('game');
modal('تقرير المباراة',`<div style="text-align:center"><div style="display:flex;justify-content:center;gap:16px;align-items:center"><b style="width:180px;text-align:left">${E(rp.away)}</b><b class="num big" style="font-size:42px">${rp.score[1]} - ${rp.score[0]}</b><b style="width:180px;text-align:right">${E(rp.home)}</b></div></div>
<div class="cols" style="margin-top:14px"><div class="card" style="padding:12px"><h3 style="padding:0 0 6px">أبرز اللاعبين</h3>${rp.top.map(p=>`<div class="pl-row"><b>${E(p.name)}</b><span class="sp"></span>${p.goals?`⚽${p.goals} `:''}${p.assists?`🅰${p.assists} `:''}<span class="ovr num h">${p.rating}</span></div>`).join('')}<div class="muted" style="padding-top:8px">رجل المباراة: ${E(rp.motm||'—')}</div></div>
<div class="card" style="padding:12px"><h3 style="padding:0 0 6px">الإحصاءات</h3>${(()=>{const a=rp.team_stats[0],b=rp.team_stats[1];const row=(l,k,f=x=>x)=>`<div class="stat"><b class="num">${f(b[k])}</b><span>${l}</span><b class="num">${f(a[k])}</b></div>`;return row('الاستحواذ','possession',x=>x+'%')+row('التسديدات','shots')+row('على المرمى','on_target')+row('الأهداف المتوقعة','xg')+row('الركنيات','corners')+row('الأخطاء','fouls')})()}</div></div>`,[{t:'متابعة',pri:1,f:()=>{closeModal();CM.render()}}],{w:760});CM.render()}
Object.assign(CM,{startMatch})})();
