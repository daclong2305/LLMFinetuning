const $ = (id) => document.getElementById(id);
let info;
let busy = false;

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function notice(text, kind='error') {
  $('notice').textContent = text;
  $('notice').className = text ? `notice ${kind}` : 'notice hidden';
}
async function api(route, body) {
  const response = await fetch(route, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function setBusy(value) {
  busy = value;
  $('ask').disabled = value;
  $('execute').disabled = value;
  $('loading').classList.toggle('hidden', !value);
}
function renderExecution(execution) {
  const area = $('table');
  area.replaceChildren();
  $('row-count').textContent = '';
  if (!execution || execution.status !== 'ok') {
    area.append(el('p',execution?.error || 'Chưa có kết quả thực thi.','muted'));
    $('table-note').textContent = 'Có thể sửa SQL ở bên trái và chạy lại.';
    return;
  }
  $('row-count').textContent = `${execution.rows.length}${execution.truncated ? '+' : ''} dòng`;
  if (!execution.rows.length) area.append(el('p','Truy vấn trả về 0 dòng. Kết quả rỗng không mặc nhiên là lỗi.','muted'));
  else {
    const table = el('table');
    const header = el('tr');
    execution.columns.forEach((column)=>header.append(el('th',column)));
    const head = el('thead'); head.append(header); table.append(head);
    const body = el('tbody');
    execution.rows.forEach((row)=>{
      const tr=el('tr');
      row.forEach((value)=>tr.append(el('td', typeof value==='number' ? new Intl.NumberFormat('vi-VN',{maximumFractionDigits:3}).format(value) : value===null ? 'NULL' : String(value), typeof value==='number' ? 'number' : '')));
      body.append(tr);
    });
    table.append(body); area.append(table);
  }
  $('table-note').textContent = execution.truncated ? 'Chỉ hiển thị 200 dòng đầu. SQL được giữ nguyên; không tự thêm LIMIT.' : 'Số tiền trong dữ liệu có đơn vị VND. Hãy đối chiếu SQL với ý nghĩa câu hỏi.';
}
function renderResult(data) {
  $('result').classList.remove('hidden');
  $('result-badge').textContent = data.status === 'ok' ? (data.backend==='offline' ? 'Ví dụ offline' : 'Ollama · Đã thực thi') : 'Cần kiểm tra';
  $('result-badge').className = 'status-pill'+(data.status==='ok'?'':' error');
  $('sql').value = data.sql || '';
  $('explanation').textContent = data.explanation || '';
  $('metrics').replaceChildren();
  const cards = [['Thời gian toàn pipeline',`${(data.duration_ms/1000).toFixed(2)} s`], ['Token đầu vào', data.input_tokens ?? '—'], ['Token đầu ra',data.output_tokens ?? '—'], ['Lượt sinh / sửa SQL',data.attempts.length]];
  cards.forEach(([name,value])=>{const card=el('div',undefined,'metric');card.append(el('span',name),el('strong',value));$('metrics').append(card);});
  renderExecution(data.execution);
  $('prompt').textContent = data.attempts.length ? data.attempts.map((a,i)=>`===== LƯỢT ${i+1} =====\n`+a.messages.map(m=>`[${m.role.toUpperCase()}]\n${m.content}`).join('\n\n')).join('\n\n') : data.messages.map(m=>`[${m.role.toUpperCase()}]\n${m.content}`).join('\n\n');
  $('trace-summary').textContent = `${data.selected_tables.length} bảng · ${data.examples.length} ví dụ · ${data.attempts.length} lượt`;
  $('trace').replaceChildren();
  const steps = [ ['Schema được dùng',data.selected_tables.join(' → ')], ['Prompt và ví dụ',data.examples.length ? data.examples.join(' / ') : 'Zero-shot: không thêm ví dụ.'] ];
  steps.forEach(([title,desc],i)=>{const step=el('div',undefined,'trace-step');const content=el('div');content.append(el('strong',title),el('p',desc));step.append(el('span',i+1,'step-number'),content);$('trace').append(step);});
  data.attempts.forEach((attempt,i)=>{const step=el('div',undefined,'trace-step');const content=el('div');content.append(el('strong',i===0?'Sinh SQL & thực thi':`Sửa SQL lần ${i}`),el('pre',attempt.sql));content.append(el('p',attempt.execution.status==='ok'?`Thực thi thành công · ${attempt.execution.duration_ms} ms`:attempt.execution.error,attempt.execution.status==='ok'?'':'error'));step.append(el('span',i+3,'step-number'),content);$('trace').append(step);});
  if (data.backend === 'offline') notice('Đang dùng SQL tham chiếu của bộ ví dụ cố định; không gọi LLM. Các tùy chọn prompt không làm thay đổi SQL trong chế độ này.','info');
  else notice(data.error || '');
}
async function ask() {
  if (busy) return;
  if (!$('question').value.trim()) {notice('Hãy nhập một câu hỏi hoặc chọn câu hỏi mẫu.');$('question').focus();return;}
  setBusy(true);notice('');$('result').classList.add('hidden');
  try {
    renderResult(await api('/api/query',{question:$('question').value,backend:$('backend').value,few_shot:$('few-shot').checked,linking:$('linking').checked,repair:$('repair').checked}));
  } catch (e) {notice(e.message);} finally {setBusy(false);}
}
async function init() {
  try {
    info=await api('/api/info');
    $('dataset-description').textContent=info.dataset;
    for (const [name,count] of Object.entries(info.counts)) {
      const card=el('div',undefined,'count');card.append(el('strong',count),el('span',name));$('counts').append(card);
    }
    for (const [name,table] of Object.entries(info.schema)) {
      const details=el('details');details.append(el('summary',name));details.append(el('pre',table.columns.map(c=>`${c.pk?'🔑 ':''}${c.name} · ${c.type}`).join('\n')+'\n'+table.foreign_keys.map(f=>`${f.from} → ${f.table}.${f.to}`).join('\n')));$('schema').append(details);
    }
    info.examples.forEach(question=>{const button=el('button',question);button.addEventListener('click',()=>{$('question').value=question;$('question').focus();});$('examples').append(button);});
    $('question').value=info.examples[0];
    $('model-status').textContent=info.ollama.available ? `● ${info.ollama.model} · ${info.ollama.compute}` : 'Ollama chưa sẵn sàng';
    if (!info.ollama.available) { $('model-status').classList.add('error');notice('Chạy start-demo.ps1 để khởi động Ollama và kiểm tra model. Có thể chọn ví dụ offline để xem luồng minh họa.','info'); }
  } catch (e) {notice(e.message);}
}
$('ask').addEventListener('click',ask);
$('question').addEventListener('keydown',(e)=>{if(e.ctrlKey && e.key==='Enter')ask();});
$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('sql').value);$('copy').textContent='Đã sao chép';setTimeout(()=>$('copy').textContent='Sao chép',1500);}catch{$('sql').select();notice('Chọn SQL và nhấn Ctrl+C để sao chép.','info');}});
$('execute').addEventListener('click',async()=>{if(busy)return;setBusy(true);try{const result=await api('/api/sql',{sql:$('sql').value});renderExecution(result);notice(result.error||'');$('explanation').textContent='Bạn vừa thực thi SQL chỉnh sửa. Token và trace hiển thị thuộc lượt sinh LLM trước đó.';$('result-badge').textContent=result.status==='ok'?'SQL chỉnh sửa · Đã thực thi':'SQL chỉnh sửa · Lỗi';$('result-badge').className='status-pill'+(result.status==='ok'?'':' error');}catch(e){notice(e.message);}finally{setBusy(false);}});
$('backend').addEventListener('change',()=>notice($('backend').value==='offline'?'Offline chỉ dùng câu hỏi mẫu. Chọn Ollama để hỏi tự do.':'' ,'info'));
init();
