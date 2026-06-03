const API=location.hostname==='localhost'?'/api':'http://localhost:8000/api';
let ds='ecommerce_db';

// ══════════════════════════════════════════════════════════════
// LangGraph flowchart — 15 real nodes
// Horizontal lanes with explicit edge routing to avoid overlaps.
// ══════════════════════════════════════════════════════════════

const SVG_W=1040, SVG_H=700;
const CW=132, CH=64;

const NODES = [
  {id:'answer_non_data',   em:'💬', lb:'非数据回答',   cx:170, cy:118, lane:'side'},
  {id:'decompose',         em:'🧩', lb:'拆解问题',     cx:462, cy:118, lane:'side'},
  {id:'orchestrator',      em:'🎯', lb:'编排执行',     cx:616, cy:118, lane:'side'},
  {id:'detect_intent',     em:'🔍', lb:'意图识别',     cx:170, cy:280, lane:'main'},
  {id:'classify',          em:'🏷️', lb:'复杂度分类',   cx:316, cy:280, lane:'main'},
  {id:'semantic',          em:'📝', lb:'语义解析',     cx:462, cy:280, lane:'main'},
  {id:'schema',            em:'🗄️', lb:'Schema 检索',  cx:616, cy:280, lane:'main'},
  {id:'sql_gen',           em:'⚡', lb:'生成 SQL',     cx:770, cy:280, lane:'main'},
  {id:'sql_review',        em:'🔍', lb:'SQL 审查',     cx:924, cy:280, lane:'main'},
  {id:'validate',          em:'🛡️', lb:'SQL 校验',     cx:924, cy:428, lane:'exec'},
  {id:'execute',           em:'▶️', lb:'执行查询',     cx:770, cy:428, lane:'exec'},
  {id:'answer',            em:'💬', lb:'汇总回答',     cx:616, cy:428, lane:'exec'},
  {id:'answer_valid_fail', em:'❌', lb:'校验失败',     cx:616, cy:590, lane:'fail'},
  {id:'sql_repair',        em:'🔧', lb:'ReAct 修复',   cx:770, cy:590, lane:'fail'},
  {id:'answer_exec_fail',  em:'❌', lb:'执行失败',     cx:924, cy:590, lane:'fail'},
];

const POS = {};
NODES.forEach(n => {
  POS[n.id] = {cx:n.cx, cy:n.cy, lane:n.lane};
});

const EDGES = [
  {f:'START',         t:'detect_intent',      d:'M58 280 L98 280'},
  {f:'detect_intent', t:'classify',           c:'是数据问题', d:'M236 280 L250 280'},
  {f:'detect_intent', t:'answer_non_data',    c:'非数据',     d:'M170 248 L170 150', lx:184, ly:202, ta:'start'},
  {f:'classify',      t:'semantic',           c:'简单',       d:'M382 280 L396 280'},
  {f:'classify',      t:'decompose',          c:'复杂',       d:'M316 248 L316 118 L396 118', lx:328, ly:168, ta:'start'},
  {f:'decompose',     t:'orchestrator',       d:'M528 118 L550 118'},
  {f:'orchestrator',  t:'END',                d:'M682 118 L734 118'},
  {f:'semantic',      t:'schema',             d:'M528 280 L550 280'},
  {f:'schema',        t:'sql_gen',            d:'M682 280 L704 280'},
  {f:'sql_gen',       t:'sql_review',         d:'M836 280 L858 280'},
  {f:'sql_review',    t:'validate',           d:'M924 312 L924 396'},
  {f:'validate',      t:'execute',            c:'通过',       d:'M858 428 L836 428'},
  {f:'validate',      t:'answer_valid_fail',  c:'失败',       d:'M924 460 L924 536 L616 536 L616 558', lx:936, ly:504, ta:'start'},
  {f:'execute',       t:'answer',             c:'成功',       d:'M704 428 L682 428'},
  {f:'execute',       t:'sql_repair',         c:'失败<3',     d:'M770 460 L770 558', lx:784, ly:512, ta:'start'},
  {f:'execute',       t:'answer_exec_fail',   c:'失败≥3',     d:'M820 460 L820 502 L1000 502 L1000 558 L924 558', lx:932, ly:492, ta:'start'},
  {f:'sql_repair',    t:'execute',            c:'重试',       d:'M704 590 L690 590 L690 460 L770 460', lx:678, ly:522, ta:'end'},
  {f:'sql_repair',    t:'answer_exec_fail',   c:'放弃',       d:'M836 590 L858 590'},
  {f:'answer',        t:'END',                d:'M616 460 L616 512'},
  {f:'answer_non_data',   t:'END',            d:'M236 118 L288 118'},
  {f:'answer_valid_fail', t:'END',            d:'M616 622 L616 662'},
  {f:'answer_exec_fail',  t:'END',            d:'M924 622 L924 662'},
];

let visited=[], current=null, isComplex=false;

// ══════════════════════════════════════════════════════════════
// SVG build
// ══════════════════════════════════════════════════════════════

function buildSvg(){
  const svg=document.getElementById('graphSvg');
  let h='';
  svg.setAttribute('viewBox', `0 0 ${SVG_W} ${SVG_H}`);

  h+=`<defs>
    <marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto" markerUnits="strokeWidth">
      <path d="M0 0 L10 4 L0 8 Z" class="ge-arrow"/>
    </marker>
  </defs>`;

  h+=`<g class="flow-lanes">
    <rect x="28" y="56" width="984" height="120" rx="18" class="lane-bg lane-side"/>
    <rect x="28" y="214" width="984" height="120" rx="18" class="lane-bg lane-main"/>
    <rect x="28" y="362" width="984" height="120" rx="18" class="lane-bg lane-exec"/>
    <rect x="28" y="526" width="984" height="118" rx="18" class="lane-bg lane-fail"/>
    <text x="48" y="78" class="lane-label">BRANCH</text>
    <text x="48" y="236" class="lane-label">MAIN PIPELINE</text>
    <text x="48" y="384" class="lane-label">RUN & ANSWER</text>
    <text x="48" y="548" class="lane-label">REPAIR / FAILURE</text>
  </g>`;

  // Draw edges
  EDGES.forEach(e => {
    const edgeClass=e.t==='END'?'ge ge-end':(e.f==='sql_repair'&&e.t==='execute'?'ge ge-loop':'ge');
    h+=`<path id="E_${e.f}_${e.t}" d="${e.d}" class="${edgeClass}" marker-end="url(#arrow)"/>`;
    if(e.c){
      const lx=e.lx ?? ((POS[e.f]?.cx || 0) + (POS[e.t]?.cx || 0)) / 2;
      const ly=e.ly ?? ((POS[e.f]?.cy || 0) + (POS[e.t]?.cy || 0)) / 2 - 10;
      const ta=e.ta || 'middle';
      h+=`<text id="L_${e.f}_${e.t}" class="ge-cond" x="${lx}" y="${ly}" text-anchor="${ta}">${e.c}</text>`;
    }
  });

  const endCaps=[
    {id:'orchestrator', x:760, y:118},
    {id:'answer_non_data', x:316, y:118},
    {id:'answer', x:616, y:536},
    {id:'answer_valid_fail', x:616, y:680},
    {id:'answer_exec_fail', x:924, y:680},
  ];
  endCaps.forEach(e=>{
    h+=`<g id="N_END_${e.id}" class="gn-end"><rect x="${e.x-18}" y="${e.y-10}" width="36" height="20" rx="10" class="gn-end-bg"/><text x="${e.x}" y="${e.y+4}" class="gn-end-txt">END</text></g>`;
  });

  // START marker
  h+=`<g id="N_START"><rect x="22" y="264" width="52" height="32" rx="16" class="gn-start-bg"/><text x="48" y="284" text-anchor="middle" class="gn-start-txt">START</text></g>`;

  // Node cards
  NODES.forEach(n => {
    const p=POS[n.id], x=p.cx-CW/2, y=p.cy-CH/2;
    h+=`<g id="N_${n.id}" class="gn">`;
    h+=`<rect x="${x}" y="${y}" width="${CW}" height="${CH}" rx="10" class="gn-bg"/>`;
    h+=`<rect x="${x+4}" y="${y+7}" width="3.5" height="${CH-14}" rx="1.5" class="gn-bar"/>`;
    h+=`<text x="${p.cx}" y="${y+28}" text-anchor="middle" font-size="18" class="gn-em">${n.em}</text>`;
    h+=`<text x="${p.cx}" y="${y+50}" text-anchor="middle" font-size="13" font-weight="700" font-family="Inter,sans-serif" class="gn-lb">${n.lb}</text>`;
    h+=`<rect x="${x+14}" y="${y+CH-7}" width="${CW-28}" height="3" rx="1.5" class="gn-pb"/>`;
    h+=`</g>`;
  });

  svg.innerHTML=h;
  resetGraph();
}
buildSvg();

// ══════════════════════════════════════════════════════════════
// State machine
// ══════════════════════════════════════════════════════════════

function $(sel){return document.querySelectorAll(sel)}
function $1(id){return document.getElementById(id)}

function resetGraph(){
  $('.gn').forEach(g=>g.setAttribute('data-state','pending'));
  $('.ge,.ge-cond,.ge-dot,.ge-loop,.ge-loop-tag').forEach(l=>l.setAttribute('data-lit','0'));
  visited=[]; current=null; isComplex=false;
}

function setState(id, state){
  const g=$1('N_'+id);
  if(g) g.setAttribute('data-state', state);
  if(state==='active') current=id;
}

function lightEdge(f,t){
  const el=$1('E_'+f+'_'+t);
  if(el) el.setAttribute('data-lit','1');
  const label=$1('L_'+f+'_'+t);
  if(label) label.setAttribute('data-lit','1');
}

function nodeEvent(name){
  if(name==='detect_intent' && visited.length===0) resetGraph();
  if(visited.includes(name)) return;
  if(current && current!==name) setState(current, 'done');
  visited.push(name);
  if(name==='decompose'||name==='orchestrator') isComplex=true;
  setState(name, 'active');
  for(let i=1; i<visited.length; i++) lightEdge(visited[i-1], visited[i]);
  if(visited.length===1) lightEdge('START', visited[0]);
  dimSkipped(name);
}

// Only dim peer branches when a fork is resolved
function dimSkipped(nodeName){
  // Fork 1: detect_intent → classify | answer_non_data
  if(nodeName==='classify'){
    setState('answer_non_data','skipped');
  }
  // Fork 2: classify → semantic (simple) | decompose (complex)
  if(nodeName==='semantic'){
    setState('decompose','skipped');
    setState('orchestrator','skipped');
  }
  if(nodeName==='decompose'){
    ['semantic','schema','sql_gen','sql_review','validate','execute','answer'].forEach(id=>setState(id,'skipped'));
  }
  // Fork 3: validate → execute | answer_valid_fail
  if(nodeName==='execute'){
    setState('answer_valid_fail','skipped');
  }
  // Fork 4: execute → answer | sql_repair | answer_exec_fail
  if(nodeName==='answer'){
    setState('sql_repair','skipped');
    setState('answer_exec_fail','skipped');
  }
}

function doneAll(){
  $('.gn').forEach(g=>{
    const s=g.getAttribute('data-state');
    if(s==='pending'||s==='active') g.setAttribute('data-state','done');
  });
  $('.ge,.ge-cond,.ge-dot,.ge-loop,.ge-loop-tag')
    .forEach(l=>l.setAttribute('data-lit','1'));
  const pc=$1('progressCard');
  if(!pc) return;
  pc.style.opacity='0'; pc.style.maxHeight='0'; pc.style.marginBottom='0';
  setTimeout(()=>{
    pc.style.display='none';
    ['sqlCard','answerCard'].forEach(id=>{const c=$1(id); if(c)c.style.display='block'});
  },400);
}

// ── Schema ──
async function loadSchema(){
  const el=$1('schemaList');
  el.innerHTML='<div class="loading">Loading...</div>';
  try{
    const r=await fetch(API+'/schema?datasource_id='+ds);
    const d=await r.json();
    let html='';
    for(const t of d.tables){
      html+=`<div class="tbl"><div class="tbl-name" onclick="tg('cols_${t.table_name}')"><span class="caret" id="caret_cols_${t.table_name}">▶</span>${t.table_name}<span class="meta">${t.row_count||'?'}R ${t.columns.length}C</span></div><div class="tbl-cols" id="cols_${t.table_name}">`;
      for(const c of t.columns){
        html+=`<div class="col-line">${c.is_primary_key?'<span class="pk">PK</span>':''}${c.column_name}<span class="type">${c.type}</span></div>`;
        if(c.sample_values&&c.sample_values.length)html+=`<span class="col-sample">${c.sample_values.slice(0,2).join(', ')}</span>`;
      }
      html+='</div></div>';
    }
    el.innerHTML=html;
    // 示例问题: pie, pie, line, line, bar, bar
    const qs=[];
    qs.push('各品类的商品数量占比');   // → 饼图（品类数少）
    qs.push('各状态订单的数量分布');   // → 饼图（状态数少）
    qs.push('按月份统计下单数量趋势'); // → 折线图（月份含-）
    qs.push('每日新增订单的数量变化'); // → 折线图（日期含-）
    qs.push('每个地区的客户数量统计'); // → 柱状图（地区多）
    qs.push('销售额最高的前10个商品'); // → 柱状图（10>8）
    $1('chips').innerHTML='<div class="chip-hd">示例问题</div>'+qs.map(q=>`<button class="chip" onclick="ask('${q}')">${q}</button>`).join('');
  }catch(e){el.innerHTML='<div class="loading" style="color:var(--red)">Failed to load schema</div>'}
}
function tg(id){$1(id).classList.toggle('open');$1('caret_'+id).classList.toggle('open')}
function onDS(){ds=$1('ds').value;loadSchema();addMsg('已切换数据源')}

// ── Chat ──
function ask(q){
  const question=q||$1('qInput').value.trim();
  if(!question)return;
  if(!q)$1('qInput').value='';
  addMsg(question,true);setBusy(true);hideBlocks();
  $1('emptyState').style.display='none';
  const pc=$1('progressCard');
  pc.style.display='block';pc.style.maxHeight='700px';pc.style.opacity='1';pc.style.marginBottom='';
  resetGraph();
  fetch(API+'/text2sql/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:'demo',question,datasource_id:ds,session_id:'demo'})})
  .then(async resp=>{
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    const reader=resp.body.getReader();const dec=new TextDecoder();let buf='',fSql='',fAns='',fRows=[],fConf=0;
    while(true){const{done,value}=await reader.read();if(done)break;
    buf+=dec.decode(value,{stream:true});const ls=buf.split('\n');buf=ls.pop()||'';
    for(const l of ls){if(!l.startsWith('data:'))continue;try{const ev=JSON.parse(l.slice(5).trim());
    if(ev.type==='start'){nodeEvent('detect_intent')}
    else if(ev.type==='node'){
      nodeEvent(ev.node);
      if(ev.sql){fSql=ev.sql;$1('sqlCard').style.display='block';$1('sqlBlock').innerHTML=hlSQL(ev.sql)}
      if(ev.answer){fAns=ev.answer;$1('answerCard').style.display='block';$1('answerBlock').textContent=ev.answer}
      if(ev.rows&&ev.rows.length){fRows=ev.rows;$1('tableCard').style.display='block';$1('rowCount').textContent='['+(ev.row_count||ev.rows.length)+' rows]';renderTable(ev.rows)}
      if(ev.confidence!=null)fConf=ev.confidence;
    }else if(ev.type==='done'){doneAll()}
    }catch(e){}}}
    setBusy(false);
    if(fRows&&fRows.length)renderChart(fRows);
    if(!fAns)fAns='查询完成';addMsg(fAns);
    if(fConf){$1('confBar').style.display='flex';$1('confFill').style.width=Math.round(fConf*100)+'%';$1('confText').textContent=Math.round(fConf*100)+'%'}
  }).catch(err=>{setBusy(false);$1('progressCard').style.display='none';toast('Connection Refused — 确认后端已启动')});
}
function addMsg(txt,isUser){const d=document.createElement('div');d.className='msg '+(isUser?'user':'ai');d.textContent=txt;const c=$1('chatMsgs');c.appendChild(d);c.scrollTop=c.scrollHeight}
function setBusy(b){$1('sendBtn').disabled=b;const d=$1('dot');d.className='status-dot '+(b?'busy':'online');$1('statusLabel').textContent=b?'BUSY':'ONLINE'}
function hideBlocks(){['sqlCard','answerCard','chartCard','tableCard','confBar'].forEach(id=>{const c=$1(id);if(c)c.style.display='none'})}
function hlSQL(s){return s.replace(/\b(SELECT|FROM|WHERE|AND|OR|JOIN|INNER|LEFT|RIGHT|ON|GROUP|BY|ORDER|ASC|DESC|LIMIT|HAVING|COUNT|SUM|AVG|MAX|MIN|AS|DISTINCT|IN|NOT|NULL|IS|LIKE|BETWEEN|CASE|WHEN|THEN|ELSE|END|UNION|ALL|EXISTS|CREATE|TABLE|INSERT|UPDATE|DELETE|DROP|ALTER|INDEX|PRIMARY|KEY|FOREIGN|REFERENCES|INTO|VALUES|SET)\b/gi,'<span class="sql-kw">$1</span>').replace(/'[^']*'/g,'<span class="sql-str">$&</span>').replace(/\b(\d+\.?\d*)\b/g,'<span class="sql-num">$1</span>')}
function renderTable(rows){const cols=Object.keys(rows[0]);const t=$1('dataTable');t.innerHTML='<thead><tr>'+cols.map(c=>'<th>'+c+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>{const v=r[c];return'<td class="'+(typeof v==='number'?'num':'')+'">'+(v===null?'<span style="color:var(--text-dim)">null</span>':v)+'</td>'}).join('')+'</tr>').join('')+'</tbody>'}
function toast(m){const t=$1('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',4000)}

// ── Charts ──
function renderChart(rows){
  const cols=Object.keys(rows[0]);
  if(cols.length<2||rows.length<1)return;
  let catCol=null,numCol=null,timeCol=null;
  for(const c of cols){const v=rows[0][c];if(typeof v==='string'&&!catCol)catCol=c;else if(typeof v==='number'&&!numCol)numCol=c;if(typeof v==='string'&&(v.includes('-')||v.includes(':'))&&!timeCol)timeCol=c}
  if(!catCol||!numCol)return;
  let ct='bar',co={};if(timeCol&&catCol===timeCol){ct='line';catCol=timeCol;co={smooth:true,symbol:'circle',symbolSize:4}}else if(rows.length<=8&&catCol&&numCol){ct='pie'}
  $1('chartCard').style.display='block';
  setTimeout(()=>{
    const dom=$1('chartBox');let c=echarts.getInstanceByDom(dom);if(c)c.dispose();c=echarts.init(dom);
    const catData=rows.map(r=>String(r[catCol]||''));
    const o={tooltip:{trigger:ct==='pie'?'item':'axis'}};
    if(ct!=='pie'){
      o.grid={left:80,right:20,top:20,bottom:ct==='bar'?80:40};
      o.xAxis={type:'category',data:catData,axisLabel:{color:'#6b7280',fontSize:11,rotate:ct==='bar'?35:0,overflow:'truncate',width:ct==='bar'?100:undefined}};
      o.yAxis={type:'value',axisLabel:{color:'#6b7280',fontSize:11},splitLine:{lineStyle:{color:'rgba(255,255,255,0.04)'}}};
    }
    if(ct==='pie')o.series=[{type:'pie',radius:['40%','70%'],data:rows.map(r=>({name:r[catCol],value:r[numCol]})),label:{color:'#6b7280',fontSize:11}}];
    else if(ct==='line')o.series=[{type:'line',data:rows.map(r=>r[numCol]),...co,lineStyle:{color:'#3b82f6',width:2},itemStyle:{color:'#3b82f6'},areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(59,130,246,0.3)'},{offset:1,color:'rgba(6,182,212,0.02)'}])}}];
    else o.series=[{type:'bar',data:rows.map(r=>r[numCol]),itemStyle:{borderRadius:[4,4,0,0],color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'#3b82f6'},{offset:1,color:'#06b6d4'}])}}];
    c.setOption(o,true);window.addEventListener('resize',()=>c.resize());
  },200);
}

(async function ping(){try{const r=await fetch('/health');if(r.ok){$1('dot').className='status-dot online';$1('statusLabel').textContent='ONLINE'}}catch(e){$1('dot').className='status-dot';$1('dot').style.background='var(--red)';$1('statusLabel').textContent='OFFLINE'};setTimeout(ping,30000)})();
loadSchema();
