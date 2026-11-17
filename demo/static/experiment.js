"use strict";
(() => {
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const state = { info: null, samples: [], source: "dataset", comparison: null, job: null, poll: null, searchTimer: null, sampleRequest: 0, busy: false, previewBusy: false, starting: false };
  let promptSample = null;
  let promptData = [], promptPreview = false, sequenceId = null, sequenceTimer = null, sequenceDone = -1;
  const cumulativeIds = ["p0", "p1", "p2", "p3", "p4"];
  const scoreKeys = ["em", "cm", "ex", "ts", "ves"];
  const safe = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const numeric = value => typeof value === "number" && Number.isFinite(value);
  const number = (value, decimals = 0) => numeric(value) ? value.toLocaleString("vi-VN", { maximumFractionDigits: decimals }) : "N/A";
  const percentage = value => numeric(value) || typeof value === "boolean" ? `${number(Number(value) * 100, 1)}%` : "N/A";
  const score = (key, value) => key === "ves" ? number(value, 3) : percentage(value);
  const duration = value => numeric(value) ? value >= 1000 ? `${number(value / 1000, 2)} s` : `${number(value, value < 10 ? 2 : 0)} ms` : "N/A";
  const money = value => numeric(value) ? `$${value.toLocaleString("en-US", { minimumFractionDigits: value > 0 ? 4 : 2, maximumFractionDigits: 6 })}` : "N/A";
  const pretty = value => typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const selected = selector => $$(selector).filter(input => input.checked && !input.disabled).map(input => input.value);
  const modelLabel = id => state.info?.models?.find(model => model.id === id)?.label || id || "Mô hình";
  const statusLabels = { ready: "Sẵn sàng", completed: "Hoàn tất", complete: "Hoàn tất", success: "Thành công", ok: "Thành công", error: "Lỗi", failed: "Thất bại", unavailable: "Chưa sẵn sàng", pending: "Đang chờ", queued: "Đang chờ", running: "Đang chạy", cancelled: "Đã hủy", cancel_requested: "Đang hủy", partial: "Chưa hoàn tất", interrupted: "Bị gián đoạn" };
  const statusBadge = status => `<span class="badge ${["failed", "error"].includes(status) ? "error" : ["unavailable", "cancelled", "partial", "interrupted"].includes(status) ? "warn" : ["running", "pending", "queued"].includes(status) ? "neutral" : ""}">${safe(statusLabels[status] || status || "Chưa đo")}</span>`;
  const notice = (element, message, error = false) => { element.textContent = message; element.classList.toggle("error", error); };
  async function api(path, body) {
    const response = await fetch(`/api/experiment/${path}`, { method: body ? "POST" : "GET", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    let result;
    try { result = await response.json(); } catch { throw new Error(`Máy chủ trả về dữ liệu không hợp lệ (HTTP ${response.status}).`); }
    if (!response.ok || (result.error && !result.id && !result.results)) throw new Error(typeof result.error === "string" ? result.error : result.error?.message || result.message || `HTTP ${response.status}`);
    return result;
  }
  function presets() {
    const data = state.info?.presets || [];
    return Array.isArray(data) ? data.map(preset => typeof preset === "string" ? { id: preset, label: preset } : preset) : Object.entries(data).map(([id, value]) => ({ id, ...(typeof value === "object" ? value : { label: value }) }));
  }
  function options() { return Object.fromEntries(["c1", "c2", "c3", "c4"].map(key => [key, $(`#${key}`).checked])); }
  function currentSample() { return state.samples.find(sample => String(sample.id) === $("#sample-select").value); }
  function dbId() { return state.source === "dataset" ? currentSample()?.db_id : $("#custom-db").value.trim(); }
  function updateButtons() {
    const questionReady = state.source === "dataset" ? !!currentSample() : !!$("#custom-question").value.trim() && !!dbId();
    $("#compare-button").disabled = state.busy || !selected(".compare-model").length || !questionReady;
    const cumulative = $("#compare-mode").value === "cumulative";
    $("#single-options").hidden = cumulative;
    if (cumulative) $("#preset-label").textContent = "P0 → P4";
    if (cumulative && (state.source !== "dataset" || currentSample()?.split !== "dev")) $("#compare-button").disabled = true;
    $("#prompt-preview-button").disabled = state.busy || state.previewBusy || !currentSample() || state.source !== "dataset";
    $("#schema-button").disabled = !dbId();
    const test = $("#benchmark-split").value === "test";
    $("#final-eval-label").hidden = !test;
    const ready = state.info?.dataset?.ready === true;
    const active = state.job && ["running", "queued", "pending", "cancel_requested"].includes(state.job.state);
    $("#benchmark-button").disabled = state.starting || !!active || !ready || !selected(".benchmark-model").length || !selected(".benchmark-preset").length || (test && !$("#final-evaluation").checked);
  }
  function renderInfo() {
    const info = state.info;
    const dataset = info.dataset || {};
    const models = info.models || [];
    const available = models.filter(model => model.available === true);
    const counts = dataset.split_counts || dataset.counts || dataset.splits || {};
    const devCount = typeof counts.dev === "object" ? counts.dev?.count ?? counts.dev?.samples : counts.dev;
    $("#dataset-health").textContent = dataset.ready ? `${number(devCount)} mẫu dev · ${dataset.name || "ViText2SQL"}` : "Chưa tải dữ liệu chính thức";
    $("#dataset-badge").className = `badge ${dataset.ready ? "" : "warn"}`;
    $("#dataset-badge").textContent = dataset.ready ? "Sẵn sàng" : "Cần thiết lập";
    $("#model-health").textContent = `${available.length}/${models.length} mô hình sẵn sàng`;
    $("#system-status").dataset.state = dataset.ready && available.length ? "ok" : "warn";
    $("#model-cards").innerHTML = models.length ? models.map(model => {
      const ready = model.available === true;
      const trained = ready && model.trained === true;
      const initial = ready && model.id === available[0]?.id;
      return `<label class="model-card ${initial ? "selected" : ready ? "" : "unavailable"}"><input class="compare-model" type="checkbox" value="${safe(model.id)}" ${initial ? "checked" : ready ? "" : "disabled"} aria-label="Chọn ${safe(model.label || model.id)}"><span class="model-body"><b>${safe(model.label || model.id)}</b><span class="model-name">${safe(model.model || model.id)}${model.provider ? `, ${safe(model.provider)}` : ""}${trained ? ", checkpoint đã xác minh" : ""}</span>${!ready ? `<span class="model-reason">Chưa sẵn sàng: ${safe(model.reason || "chưa đáp ứng điều kiện suy luận.")}</span>` : ""}</span></label>`;
    }).join("") : '<p class="muted">Chưa có mô hình. Thêm vào config/experiment.json.</p>';
    $("#benchmark-models").innerHTML = models.map(model => `<label class="check-option"><input class="benchmark-model" type="checkbox" value="${safe(model.id)}" ${model.available === true ? "checked" : "disabled"}><span>${safe(model.label || model.id)}<small>${safe(model.available === true ? model.model || model.provider : model.reason || "Chưa sẵn sàng")}</small></span></label>`).join("");
    const list = presets();
    $("#preset").innerHTML = list.map(preset => `<option value="${safe(preset.id)}">${safe(preset.label || preset.name || preset.id)}</option>`).join("") || '<option value="c0">C0 · Baseline</option>';
    $("#benchmark-presets").innerHTML = list.map((preset, index) => `<label class="check-option"><input class="benchmark-preset" type="checkbox" value="${safe(preset.id)}" ${cumulativeIds.includes(preset.id) ? "checked" : ""}><span>${safe(preset.label || preset.name || preset.id)}${preset.description ? `<small>${safe(preset.description)}</small>` : ""}</span></label>`).join("");
    $("#model-setup").innerHTML = '<p>Mặc định chọn một model để demo nhanh. Tích thêm model khi cần so sánh; các model chạy lần lượt.</p><p>Qwen base: chạy Ollama và tải đúng model đã đăng ký. Claude Haiku 4.5: thiết lập thông tin AWS và region trong <code>.env</code> (hoặc <code>env</code>), tài khoản cần quyền gọi model trên Amazon Bedrock. Qwen fine-tuned: huấn luyện và đăng ký checkpoint riêng đã có manifest.</p>';
    $("#training-info").innerHTML = `<pre>${safe(pretty(info.training || { state: "Chưa có thông tin checkpoint." }))}</pre>`;
    $("#dataset-details").innerHTML = `<details><summary>Phiên bản, kiểm tra split & khả năng thực thi</summary><pre>${safe(pretty(dataset))}</pre></details>`;
    const demoDatabases = dataset.demo_databases || [];
    $("#database-demo-status").hidden = !demoDatabases.length;
    $("#database-demo-status").textContent = `SQLite demo đã kết nối: ${demoDatabases.join(", ")}. Chọn mẫu thuộc database này để xem dữ liệu mô phỏng. EX/TS/VES vẫn là N/A.`;
    const definitions = info.metric_definitions || [];
    const entries = Array.isArray(definitions) ? definitions : Object.entries(definitions).map(([id, definition]) => ({ id, ...(typeof definition === "object" ? definition : { description: definition }) }));
    $("#metric-definitions").innerHTML = entries.length ? entries.map(definition => `<div class="metric-definition"><strong>${safe((definition.id || definition.key || definition.name || "").toUpperCase())}</strong><p>${safe(definition.description || definition.definition || definition.label || "")}${definition.requires ? `<br><span class="muted">Điều kiện: ${safe(pretty(definition.requires))}</span>` : ""}</p></div>`).join("") : '<p>EM: khớp cấu trúc SQL. CM: F1 thành phần SQL. EX: so sánh toàn bộ kết quả thực thi. TS: test-suite accuracy. VES: độ chính xác có xét hiệu quả thực thi.</p>';
    const warnings = [];
    if (!dataset.ready) warnings.push(`${dataset.reason || dataset.error || "Bộ dữ liệu chưa sẵn sàng."} Chạy scripts/prepare_vitext2sql.py để tải nguồn chính thức và kiểm tra schema.`);
    if (!available.length) warnings.push("Chưa có mô hình sẵn sàng. Kiểm tra Ollama, khóa API hoặc checkpoint tại phần thiết lập mô hình.");
    $("#global-status").hidden = !warnings.length;
    $("#global-status").textContent = warnings.join(" ");
    $$(".compare-model").forEach(input => input.addEventListener("change", () => { input.closest(".model-card").classList.toggle("selected", input.checked); updateButtons(); }));
    $$(".benchmark-model,.benchmark-preset").forEach(input => input.addEventListener("change", updateButtons));
    applyPreset();
    updateButtons();
  }
  function applyPreset() {
    const preset = presets().find(item => item.id === $("#preset").value);
    const config = preset?.options || preset || {};
    ["c1", "c2", "c3", "c4"].forEach(key => { $(`#${key}`).checked = config[key] === true; });
    $("#preset-label").textContent = $("#compare-mode").value === "cumulative" ? "P0 → P4" : preset?.id?.toUpperCase() || "C0";
  }
  async function loadSamples() {
    const request = ++state.sampleRequest;
    const split = $("#sample-split").value;
    const query = $("#sample-search").value.trim();
    $("#sample-select").innerHTML = '<option value="">Đang tải mẫu…</option>';
    state.samples = [];
    updateButtons();
    try {
      const data = await api(`samples?split=${encodeURIComponent(split)}&limit=100&offset=0&q=${encodeURIComponent(query)}`);
      if (request !== state.sampleRequest) return;
      state.samples = data.items || [];
      $("#sample-count").textContent = `(${number(data.total)} mẫu${data.total > state.samples.length ? `, hiển thị ${state.samples.length} đầu tiên` : ""})`;
      $("#sample-select").innerHTML = state.samples.length ? state.samples.map(sample => `<option value="${safe(sample.id)}">${safe(sample.question)}</option>`).join("") : '<option value="">Không có mẫu phù hợp</option>';
      renderSample();
    } catch (error) {
      if (request !== state.sampleRequest) return;
      $("#sample-count").textContent = "";
      $("#sample-select").innerHTML = '<option value="">Không thể tải mẫu</option>';
      $("#sample-preview").innerHTML = `<p class="muted">${safe(error.message)}</p><span class="tiny-note">Sau khi thiết lập dữ liệu, tải lại trang để tiếp tục. Bạn có thể xem hướng dẫn tại tab Phương pháp.</span>`;
    }
    updateButtons();
  }
  function renderSample() {
    const sample = currentSample();
    $("#sample-preview").innerHTML = sample ? `<p class="question">${safe(sample.question)}</p><p class="sample-meta"><span>Database <b>${safe(sample.db_id)}</b></span><span>Độ khó <b>${safe(sample.difficulty || "chưa phân loại")}</b></span><span>Mã <b>${safe(sample.id)}</b></span></p>` : '<p class="muted">Không có mẫu phù hợp. Đổi từ khóa tìm kiếm hoặc tập dữ liệu.</p>';
    $("#schema-details").hidden = true;
    updateButtons();
  }
  async function loadSchema() {
    const id = dbId();
    if (!id) return;
    const button = $("#schema-button");
    button.disabled = true;
    button.textContent = "Đang tải schema…";
    try {
      const result = await api(`schema?db_id=${encodeURIComponent(id)}`);
      $("#schema-db").textContent = result.db_id || id;
      const schema = result.schema || {};
      $("#schema-content").innerHTML = Object.keys(schema).length ? schemaView(schema) : '<p class="muted">Database này chưa có schema.</p>';
      $("#schema-details").hidden = false;
      $("#schema-details").open = true;
    } catch (error) { notice($("#compare-status"), `Không thể tải schema: ${error.message}`, true); }
    finally { button.textContent = "Schema"; updateButtons(); }
  }
  function schemaView(schema) {
    const tables = Object.entries(schema);
    if (!tables.every(([, table]) => Array.isArray(table?.columns))) return tables.map(([name, table]) => `<div class="schema-table"><h3>${safe(name)}</h3><pre>${safe(table?.ddl || pretty(table))}</pre></div>`).join("");
    const relations = tables.flatMap(([name, table]) => (table.foreign_keys || []).map(fk => ({ from: name, column: fk.from, to: fk.table, target: fk.to })));
    const cards = tables.map(([name, table]) => {
      const fks = Object.fromEntries((table.foreign_keys || []).map(fk => [fk.from, fk]));
      return `<figure class="er-table" data-table="${safe(name)}"><figcaption><span>${safe(name)}</span><small>${table.columns.length} cột</small></figcaption><ul>${table.columns.map(column => {
        const fk = fks[column.name];
        return `<li class="${column.pk ? "pk" : ""}${fk ? " fk" : ""}" data-col="${safe(column.name)}"${fk ? ` tabindex="0" data-ref="${safe(fk.table)}" data-ref-col="${safe(fk.to)}"` : ""}><span class="er-name">${safe(column.name)}</span>${fk ? `<span class="er-ref">→ ${safe(fk.table)}.${safe(fk.to)}</span>` : ""}<span class="er-type">${safe(column.type || "")}</span></li>`;
      }).join("")}</ul>${table.description ? `<p class="tiny-note">${safe(table.description)}</p>` : ""}</figure>`;
    }).join("");
    const relationList = relations.length ? `<ul class="er-relations">${relations.map(r => `<li><b>${safe(r.from)}</b>.${safe(r.column)} → <b>${safe(r.to)}</b>.${safe(r.target)}</li>`).join("")}</ul>` : '<p class="tiny-note">Database này không khai báo khóa ngoại.</p>';
    const ddl = tables.map(([, table]) => table.ddl).filter(Boolean).join("\n\n");
    return `<div class="er-grid">${cards}</div><p class="table-note"><b>Ghi chú.</b> ${tables.length} bảng, ${relations.length} quan hệ. Cột gạch chân là khóa chính; mũi tên là khóa ngoại trỏ tới bảng và cột đích. Di chuột hoặc focus vào khóa ngoại để làm nổi bảng đích.</p><div class="er-relations-block"><p class="detail-label">Quan hệ khóa ngoại</p>${relationList}</div>${ddl ? `<details class="ddl"><summary>DDL gốc</summary><pre>${safe(ddl)}</pre></details>` : ""}`;
  }
  function highlightReference(item, on) {
    const host = $("#schema-content");
    $$(".er-table", host).forEach(card => {
      const target = on && card.dataset.table === item.dataset.ref;
      card.classList.toggle("target", target);
      $$("li", card).forEach(li => li.classList.toggle("target", target && li.dataset.col === item.dataset.refCol));
    });
    item.classList.toggle("source", on);
  }
  const metricReason = (metrics, key) => {
    const reasons = metrics.unavailable_reasons || metrics.reasons || {};
    return typeof reasons === "string" ? reasons : reasons[key] || reasons.evaluation || "Chưa có phép đo hoặc tài sản đánh giá phù hợp.";
  };
  function executionView(execution) {
    const note = execution?.synthetic ? `<p class="tiny-note"><span class="badge warn">Dữ liệu demo</span> ${safe(execution.note)}</p>` : "";
    return note + executionBody(execution);
  }
  function executionBody(execution) {
    if (!execution) return '<p class="muted">Chưa có kết quả thực thi. EX yêu cầu database SQLite có dữ liệu phù hợp.</p>';
    if (execution.error) return `<p class="result-error">${safe(execution.error)}</p>`;
    if (execution.mode === "schema_only" || execution.status === "schema_only") return `<p class="muted">${safe(execution.note || "Chỉ xác thực cú pháp/schema. Chưa có database chứa dữ liệu để trả kết quả hoặc đo EX.")}</p>`;
    const rows = execution.rows || execution.data || [];
    const columns = execution.columns || (rows[0] && !Array.isArray(rows[0]) ? Object.keys(rows[0]) : []);
    if (!Array.isArray(rows)) return `<pre>${safe(pretty(execution))}</pre>`;
    if (!rows.length) return `<p>Truy vấn trả về 0 dòng${execution.success === false ? " hoặc không thực thi thành công" : ""}.</p>`;
    return `<p class="tiny-note">Xem trước ${Math.min(rows.length, 20)} dòng${numeric(execution.row_count) ? ` / ${number(execution.row_count)}` : ""}. Preview không được dùng làm điểm EX.</p><div class="table-scroll"><table>${columns.length ? `<thead><tr>${columns.map(column => `<th>${safe(typeof column === "object" ? column.name : column)}</th>`).join("")}</tr></thead>` : ""}<tbody>${rows.slice(0, 20).map(row => `<tr>${(Array.isArray(row) ? row : columns.map(column => row[column])).map(cell => `<td>${safe(cell === null ? "NULL" : typeof cell === "object" ? pretty(cell) : cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function traceView(trace) {
    if (!trace || !trace.length) return '<p class="muted">Chưa có trace.</p>';
    return trace.map((stage, index) => `<div class="trace-stage"><h4>${index + 1}. ${safe(stage.stage || stage.name || stage.type || "Suy luận")}</h4><small>${safe(stage.status || "")} ${numeric(stage.latency_ms ?? stage.duration_ms) ? `· ${duration(stage.latency_ms ?? stage.duration_ms)}` : ""}${numeric(stage.input_tokens ?? stage.usage?.input_tokens) ? ` · ${number(stage.input_tokens ?? stage.usage?.input_tokens)} input tokens` : ""}</small>${stage.error ? `<p class="result-error">${safe(stage.error)}</p>` : ""}<details><summary>Prompt, phản hồi & usage</summary><pre>${safe(pretty(stage))}</pre></details></div>`).join("");
  }
  const comparisonOpen = new Set();
  const asNumber = value => typeof value === "boolean" ? Number(value) : value;
  const bestValues = (rows, read) => Object.fromEntries(scoreKeys.map(key => {
    const values = rows.map(row => asNumber(read(row, key))).filter(numeric);
    const top = values.length ? Math.max(...values) : null;
    return [key, values.length > 1 && top > 0 && top !== Math.min(...values) ? top : null];
  }));
  const scoreText = (key, value, best) => {
    const text = score(key, value);
    return best != null && asNumber(value) === best ? `<strong class="best">${text}</strong>` : text;
  };
  function renderComparison(data) {
    state.comparison = data;
    const sample = data.sample || {};
    $("#comparison-context").hidden = false;
    $("#comparison-context").innerHTML = `Bảng 1. Kết quả cho mẫu ${safe(sample.id || "tự nhập")}${sample.db_id ? ` (${safe(sample.db_id)})` : ""}${sample.question ? `<br><span class="caption-detail">${safe(sample.question)}</span>` : ""}`;
    const results = data.results || [];
    if (results.length) setPromptData(results, false, data.sample);
    const container = $("#compare-results");
    $("#compare-export").disabled = !results.length;
    const gold = data.sample?.gold_sql;
    $("#gold-details").hidden = !gold;
    $("#gold-details").open = false;
    $("#gold-sql").textContent = gold || "";
    if (!results.length) {
      container.className = "empty-state";
      container.innerHTML = "<p>Không có kết quả trả về. Kiểm tra trạng thái mô hình rồi chạy lại.</p>";
      return;
    }
    container.className = "results-table table-scroll";
    const best = bestValues(results, (result, key) => result.metrics?.[key]);
    const head = ["Mô hình", "Cấu hình", "Trạng thái", ...scoreKeys.map(key => key.toUpperCase()), "Thời gian", "Token vào / ra", "Chi phí"];
    container.innerHTML = `<table><thead><tr>${head.map((label, index) => `<th scope="col"${index > 2 ? ' class="num"' : ""}>${label}</th>`).join("")}</tr></thead><tbody>${results.map((result, index) => {
      const metrics = result.metrics || {};
      const key = `${result.model_id}|${result.preset_id || ""}`;
      const open = comparisonOpen.has(key) || results.length === 1;
      const provider = state.info?.models?.find(model => model.id === result.model_id)?.provider;
      const missing = scoreKeys.filter(item => metrics[item] == null);
      const success = metrics.execution_success;
      const cost = `${money(metrics.cost_usd)}${metrics.cost_usd === 0 && provider === "ollama" ? " (local)" : ""}`;
      const cells = scoreKeys.map(item => metrics[item] == null ? `<td class="num na" title="${safe(metricReason(metrics, item))}">N/A</td>` : `<td class="num">${scoreText(item, metrics[item], best[item])}</td>`).join("");
      return `<tr class="result-row${open ? " open" : ""}"><td><button class="row-toggle" type="button" aria-expanded="${open}" aria-controls="result-detail-${index}" data-key="${safe(key)}"><span>${safe(result.label || modelLabel(result.model_id))}</span></button></td><td>${safe(result.preset_id ? result.preset_id.toUpperCase() : "Tùy chỉnh")}</td><td>${statusBadge(result.status)}</td>${cells}<td class="num">${duration(metrics.latency_ms)}</td><td class="num">${number(metrics.input_tokens)} / ${number(metrics.output_tokens)}</td><td class="num">${cost}</td></tr><tr class="result-detail" id="result-detail-${index}"${open ? "" : " hidden"}><td colspan="${head.length}"><div class="detail-inner"><div><p class="detail-label">SQL được sinh</p><div class="sql-block"><pre>${safe(result.sql || "Chưa sinh được SQL.")}</pre></div></div>${result.error ? `<div class="result-error">${safe(typeof result.error === "object" ? pretty(result.error) : result.error)}</div>` : ""}<div class="usage-grid"><div>Thời gian toàn pipeline<b>${duration(metrics.latency_ms)}</b></div><div>Thời gian thực thi SQL<b>${duration(metrics.sql_latency_ms)}</b></div><div>Lượt gọi / input cached<b>${number(metrics.calls)} / ${number(metrics.cached_input_tokens)}</b></div><div>Thực thi / cú pháp<b>${success == null ? "N/A" : success ? "Thành công" : "Lỗi"} / ${metrics.syntax_valid == null ? "N/A" : metrics.syntax_valid ? "Hợp lệ" : "Lỗi"}</b></div></div><details><summary>Kết quả thực thi</summary>${executionView(result.execution)}</details>${missing.length ? `<details><summary>Vì sao ${missing.length} chỉ số là N/A</summary>${missing.map(item => `<p><b>${item.toUpperCase()}</b>: ${safe(metricReason(metrics, item))}</p>`).join("")}</details>` : ""}<details><summary>Nhật ký lượt gọi và thực thi (${(result.trace || []).length} bước)</summary>${traceView(result.trace || [])}</details><details><summary>Thành phần CM và độ phủ usage</summary><p class="tiny-note">N/A ở usage nghĩa là adapter chưa trả đủ thông tin; các số đã biết vẫn được lưu.</p><pre>${safe(pretty({ cm_components: metrics.cm_components || null, calls: metrics.calls, repair_calls: metrics.repair_calls, input_tokens_coverage: metrics.input_tokens_coverage, output_tokens_coverage: metrics.output_tokens_coverage, cached_input_tokens_coverage: metrics.cached_input_tokens_coverage, cost_usd_coverage: metrics.cost_usd_coverage, known_input_tokens: metrics.known_input_tokens, known_output_tokens: metrics.known_output_tokens, known_cost_usd: metrics.known_cost_usd, options: result.options }))}</pre></details></div></td></tr>`;
    }).join("")}</tbody></table>`;
    $$(".row-toggle", container).forEach(button => button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      button.closest("tr").classList.toggle("open", open);
      $(`#${button.getAttribute("aria-controls")}`).hidden = !open;
      if (open) comparisonOpen.add(button.dataset.key); else comparisonOpen.delete(button.dataset.key);
    }));
  }
  async function compare() {
    if ($("#compare-button").disabled) return;
    if ($("#compare-mode").value === "cumulative") return startSequence();
    state.busy = true;
    updateButtons();
    $("#compare-button").innerHTML = '<span class="spinner" aria-hidden="true"></span> Đang chạy';
    $("#compare-button").setAttribute("aria-busy", "true");
    $("#compare-loading").hidden = false;
    $("#compare-results").setAttribute("aria-busy", "true");
    notice($("#compare-status"), "Thời gian chạy phụ thuộc mô hình và các kỹ thuật C1–C4 đang bật.");
    const body = { model_ids: selected(".compare-model"), options: options() };
    if (state.source === "dataset") body.sample_id = currentSample().id;
    else { body.question = $("#custom-question").value.trim(); body.db_id = dbId(); }
    try {
      const data = await api("compare", body);
      renderComparison(data);
      const errors = (data.results || []).filter(result => !["ok", "success", "completed", "complete"].includes(result.status)).length;
      notice($("#compare-status"), `Đã nhận ${data.results?.length || 0} kết quả${errors ? ` · ${errors} mô hình có lỗi hoặc chưa hoàn tất` : ""}. Run ${data.id || ""}`);
    } catch (error) { notice($("#compare-status"), `Không thể so sánh: ${error.message}`, true); }
    finally {
      state.busy = false;
      $("#compare-button").textContent = "Chạy";
      $("#compare-button").setAttribute("aria-busy", "false");
      $("#compare-loading").hidden = true;
      $("#compare-results").setAttribute("aria-busy", "false");
      updateButtons();
    }
  }
  function downloadJson(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function coverage(row, key) {
    const value = row.coverage?.[key];
    if (numeric(row.eligible_n?.[key])) return `${number(row.eligible_n[key])}/${number(row.n)} · ${percentage(value)}`;
    if (numeric(value)) return `${percentage(value)} mẫu đã đo`;
    if (value && typeof value === "object") {
      const count = value.n ?? value.count ?? value.available ?? value.evaluated;
      const total = value.total ?? row.n;
      if (numeric(count)) return `${number(count)}/${number(total)}`;
      return pretty(value);
    }
    return row[key] == null ? "0 / không có phép đo" : "chưa có số coverage";
  }
  function renderSummary(summary) {
    const rows = [...(summary?.rows || [])].sort((a,b) => a.model_id.localeCompare(b.model_id) || a.preset_id.localeCompare(b.preset_id));
    if (!rows.length) {
      $("#benchmark-chart").className = "chart-empty";
      $("#benchmark-chart").textContent = "";
      $("#benchmark-table").innerHTML = '<p class="empty-line">Chưa có kết quả. Tiến độ và kết quả một phần sẽ tự cập nhật.</p>';
      $("#difficulty-results").innerHTML = "";
      return;
    }
    $("#benchmark-chart").className = "bar-chart";
    const best = bestValues(rows, (row, key) => row[key]);
    $("#benchmark-chart").innerHTML = '<p class="caption">Hình 1. EM, CM và EX theo mô hình và cấu hình</p>' + rows.map(row => `<div class="bar-chart-row"><div class="bar-chart-name"><b>${safe(modelLabel(row.model_id))}</b><br><span class="muted">${safe(presets().find(p => p.id === row.preset_id)?.label || row.preset_id)}</span></div><div class="bars">${["em", "cm", "ex"].map(key => `<div class="bar-line"><span class="bar-key">${key.toUpperCase()}</span><div class="bar-track"><div class="bar-fill ${key}" data-width="${numeric(row[key]) ? Math.max(0, Math.min(100, row[key] * 100)) : 0}"></div></div><span class="bar-value">${percentage(row[key])}</span></div>`).join("")}</div></div>`).join("");
    $$("#benchmark-chart .bar-fill").forEach(bar => { bar.style.width = `${bar.dataset.width}%`; });
    const columns = ["Mô hình / cấu hình", "Mẫu", "EM", "CM", "EX", "TS", "VES", "Thực thi", "Cú pháp", "Thời gian p50 / p95", "SQL trung bình", "Token vào / ra", "Lượt gọi", "Chi phí API"];
    $("#benchmark-table").innerHTML = `<table><thead><tr>${columns.map(column => `<th>${column}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr><td>${safe(modelLabel(row.model_id))}<small>${safe(presets().find(p => p.id === row.preset_id)?.label || row.preset_id)}</small></td><td>${number(row.n)} / ${number(row.expected_n)}<small>đã đo / dự kiến</small></td>${scoreKeys.map(key => `<td class="num${row[key] == null ? " na" : ""}">${scoreText(key, row[key], best[key])}<small>${safe(coverage(row, key))}</small></td>`).join("")}<td>${percentage(row.execution_success_rate)}</td><td>${percentage(row.syntax_valid_rate)}</td><td>${duration(row.p50_latency_ms)} / ${duration(row.p95_latency_ms)}</td><td>${duration(row.mean_sql_latency_ms)}</td><td>${number(row.input_tokens)} / ${number(row.output_tokens)}</td><td>${number(row.calls)}</td><td>${money(row.cost_usd)}${row.cost_usd === 0 ? "<small>local</small>" : ""}</td></tr>`).join("")}</tbody></table>`;
    const table = $("table", $("#benchmark-table"));
    const cachedHead = document.createElement("th");
    cachedHead.textContent = "Input cached";
    for (const label of ["Lỗi pipeline", "Lượt sửa"]) {
      const head = document.createElement("th"); head.textContent=label; $("thead tr",table).append(head);
    }
    $("thead tr", table).append(cachedHead);
    $$("tbody tr", table).forEach((tr, index) => {
      const row = rows[index];
      for (const key of ["errors", "repair_calls"]) {
        const cell = document.createElement("td"); cell.textContent = number(row[key]); tr.append(cell);
      }
      const cachedCell = document.createElement("td");
      cachedCell.innerHTML = `${number(row.cached_input_tokens)}<small>${safe(coverage(row, "cached_input_tokens"))}</small>`;
      tr.append(cachedCell);
      scoreKeys.forEach((key, offset) => {
        const cell = tr.children[offset + 2];
        const interval = row.intervals?.[key];
        cell.title = row[key] == null ? (row.unavailable_reasons?.[key] || []).join("; ") || "Chưa có phép đo hợp lệ." : interval ? `Wilson 95%: ${percentage(interval[0])} – ${percentage(interval[1])}` : "Điểm tính trên các mẫu có phép đo hợp lệ; xem coverage.";
      });
    });
    $("#difficulty-results").innerHTML = `<details class="difficulty-block"><summary>Độ phủ, lý do N/A và khoảng tin cậy</summary><pre>${safe(pretty(rows.map(row => ({ model_id: row.model_id, preset_id: row.preset_id, errors: row.errors, complete: row.complete, coverage: row.coverage, eligible_n: row.eligible_n, intervals: row.intervals, unavailable_reasons: row.unavailable_reasons, cm_components: row.cm_components }))))}</pre></details>` + rows.filter(row => row.per_difficulty && Object.keys(row.per_difficulty).length).map(row => `<details class="difficulty-block"><summary>Theo độ khó: ${safe(modelLabel(row.model_id))}, ${safe(presets().find(p => p.id === row.preset_id)?.label || row.preset_id)}</summary><div class="table-scroll"><table><thead><tr><th>Độ khó</th><th>Mẫu</th><th>EM</th><th>CM</th><th>EX</th><th>TS</th></tr></thead><tbody>${Object.entries(row.per_difficulty).map(([difficulty,values])=>`<tr><td>${safe(difficulty)}</td><td>${number(values.n)}</td>${["em","cm","ex","ts"].map(key=>`<td>${score(key,values[key])}<small>${number(values[key+"_eligible_n"])}/${number(values.n)} đo được</small></td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`).join("") + (summary.notes?.length ? `<p class="table-note">${safe(summary.notes.join(" "))}</p>` : "");
  }
  function renderJob(job) {
    state.job = job;
    if (!$("#view-benchmark").hidden) history.replaceState(null,"",`#report/${job.id}`);
    $("#report-context").hidden = false;
    $("#report-context").innerHTML = `Bảng 2. ${job.purpose === "prompt_comparison" ? "So sánh prompt trên một câu hỏi" : "Kết quả benchmark"} trên tập ${safe(job.split || "dev")}, ${job.scope === "full" ? "toàn bộ split" : "tập con pilot"}<br><span class="caption-detail">Trạng thái: ${safe(statusLabels[job.state] || job.state)}</span>`;
    $("#report-manifest").textContent = pretty({run_id:job.id, sample_selection:job.sample_selection, sample_ids:job.sample_ids, presets:job.presets, models:job.models, runtime:job.runtime, dataset_fingerprint:job.dataset_fingerprint, code_sha256:job.code_sha256});
    $("#report-details-button").disabled = !job.done;
    if (state.reportDetailsId !== job.id) {
      $("#report-records").innerHTML = "";
      $("#report-details-button").textContent = "Xem từng mẫu và prompt";
    }
    const done = job.done || 0;
    const total = job.total || 0;
    const terminal = !["running", "pending", "queued", "cancel_requested"].includes(job.state);
    $("#job-state").outerHTML = statusBadge(job.state).replace('<span class="', '<span id="job-state" class="');
    $("#job-progress").textContent = `${number(done)}/${number(total)} lượt thí nghiệm${job.state === "cancelled" ? ", kết quả một phần" : ""}`;
    $("#job-percent").textContent = total ? percentage(done / total) : "—";
    $("#job-bar").max = Math.max(1, total);
    $("#job-bar").value = done;
    $("#job-id").textContent = job.id || "";
    $("#cancel-button").disabled = terminal || job.state === "cancel_requested";
    $("#csv-export").disabled = $("#json-export").disabled = !job.summary?.rows?.length;
    renderSummary(job.summary);
    if (job.error) notice($("#benchmark-status"), typeof job.error === "object" ? pretty(job.error) : job.error, true);
    else if (terminal) notice($("#benchmark-status"), job.state === "cancelled" ? "Run đã hủy. Kết quả đã đo được giữ lại, không đại diện cho benchmark hoàn chỉnh." : job.state === "completed" || job.state === "complete" ? "Run đã hoàn tất. Bạn có thể tải kết quả và manifest để kiểm tra khả năng so sánh." : `Run kết thúc với trạng thái: ${statusLabels[job.state] || job.state}.`);
    updateButtons();
    return terminal;
  }
  async function pollJob(id) {
    clearTimeout(state.poll);
    try {
      const job = await api(`job?id=${encodeURIComponent(id)}`);
      if (state.job && state.job.id !== id) return;
      const terminal = renderJob(job);
      if (!terminal) state.poll = setTimeout(() => pollJob(id), 1600);
      else loadRuns();
    } catch (error) {
      notice($("#benchmark-status"), `Chưa thể cập nhật tiến độ: ${error.message}. Sẽ thử lại.`, true);
      state.poll = setTimeout(() => pollJob(id), 5000);
    }
  }
  async function startBenchmark() {
    if ($("#benchmark-button").disabled) return;
    const limit = Number($("#benchmark-limit").value);
    if (!Number.isInteger(limit) || limit < 1 || limit > 10000) { notice($("#benchmark-status"), "Số mẫu phải là số nguyên từ 1 đến 10.000.", true); return; }
    state.starting = true;
    updateButtons();
    notice($("#benchmark-status"), "Đang tạo run và cố định danh sách mẫu…");
    try {
      const job = await api("benchmark", { split: $("#benchmark-split").value, limit, model_ids: selected(".benchmark-model"), preset_ids: selected(".benchmark-preset"), sample_selection: $("#sample-selection").value, final_evaluation: $("#benchmark-split").value === "test" && $("#final-evaluation").checked });
      renderJob({ ...job, done: 0 });
      pollJob(job.id);
      loadRuns();
    } catch (error) { notice($("#benchmark-status"), `Không thể bắt đầu: ${error.message}`, true); }
    finally { state.starting = false; updateButtons(); }
  }
  async function cancelBenchmark() {
    if (!state.job || $("#cancel-button").disabled) return;
    $("#cancel-button").disabled = true;
    try { await api("cancel", { id: state.job.id }); notice($("#benchmark-status"), "Đã gửi yêu cầu hủy. Lượt suy luận đang chạy có thể cần kết thúc trước khi dừng."); pollJob(state.job.id); }
    catch (error) { notice($("#benchmark-status"), `Không thể hủy run: ${error.message}`, true); $("#cancel-button").disabled = false; }
  }
  async function loadRuns() {
    try {
      const data = await api("runs");
      $("#run-history").innerHTML = data.runs?.length ? data.runs.map(run => `<div class="history-row"><div><strong>${safe(run.id)}</strong><small>${run.scope === "full" ? "FULL" : "PILOT"} · ${run.purpose === "prompt_comparison" ? "Prompt" : "Benchmark"} · ${safe(run.split || "dev")} · ${safe(run.created_at ? new Date(run.created_at).toLocaleString("vi-VN") : "Không có thời gian")} · ${run.done || 0}/${run.total || 0} kết quả</small></div><div class="history-actions">${statusBadge(run.state)}<button class="button subtle small load-run" data-run="${safe(run.id)}">Xem</button>${run.done ? `<button class="button subtle small open-log" data-run="${safe(run.id)}">Duyệt log</button>` : ""}</div></div>`).join("") : '<p class="muted">Chưa có lượt chạy nào được lưu.</p>';
      $$(".open-log").forEach(button => button.addEventListener("click", () => openLogView(button.dataset.run)));
      $$(".load-run").forEach(button => button.addEventListener("click", () => { clearTimeout(state.poll); state.job = { id: button.dataset.run }; pollJob(button.dataset.run); }));
    } catch (error) { $("#run-history").innerHTML = `<p class="muted">Không thể tải lịch sử: ${safe(error.message)}</p>`; }
  }
  async function exportRun(format) {
    if (!state.job?.id) return;
    try {
      const response = await fetch(`/api/experiment/export?id=${encodeURIComponent(state.job.id)}&format=${format}`);
      if (!response.ok) { const error = await response.json(); throw new Error(error.error || `HTTP ${response.status}`); }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `visql-${state.job.id}.${format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { notice($("#benchmark-status"), `Không thể xuất kết quả: ${error.message}`, true); }
  }

  function showView(name) {
    $$(".nav-tab").forEach(tab => { const active = tab.dataset.view === name; tab.classList.toggle("active", active); tab.setAttribute("aria-pressed", String(active)); });
    $$(".view").forEach(view => { view.hidden = view.id !== `view-${name}`; });
    if (name === "log") {
      if (logState.data) {
        mountDetail(); renderLog();
        if (["running", "pending", "queued", "cancel_requested"].includes(logState.data.run.state)) { clearTimeout(logState.timer); logState.timer = setTimeout(() => watchLog(logState.data.id), 1000); }
      }
    }
    else { unmountDetail(); clearTimeout(logState.timer); }
    history.replaceState(null, "", name === "benchmark" ? "#report" : name === "method" ? "#method" : name === "log" ? (logState.data ? `#log/${logState.data.id}` : "#log") : "#experiment");
  }
  function stagesOf(row) {
    if (row.kind === "preview") return [{stage:"generate", key:"generate:1", messages:row.messages, output:row.note}];
    const counts = {};
    return (row.trace || []).filter(t => t.model_call).map(t => { counts[t.stage] = (counts[t.stage] || 0) + 1; return {...t,key:`${t.stage}:${counts[t.stage]}`}; });
  }
  function setPromptData(rows, preview, sample) {
    promptSample = sample || null;
    const previousRow = promptData.length ? promptRow() : null;
    const previousModel = $("#prompt-model").value;
    const previousStage = $("#prompt-stage").value;
    const preserve = promptPreview === preview;
    promptData = rows;
    promptPreview = preview;
    $("#prompt-inspector").hidden = false;
    $("#prompt-kind").textContent = preview ? "Xem trước, chưa gọi model" : "Prompt đã gửi";
    $("#prompt-note").textContent = preview ? "C1/C3 chỉ là placeholder. Preview chưa có phản hồi model hoặc lỗi DB. C4 chỉ thêm lượt sửa khi có lỗi." : "Diff so với cấu hình liền trước của cùng model và cùng loại lượt gọi; riêng C4 so với lượt gọi trước trong cùng cấu hình. Xanh: thêm; đỏ: bỏ. C2 chọn schema trước khi gọi C1; C4 dùng lại schema đầy đủ khi sửa. Kế hoạch C3 là đầu ra có cấu trúc.";
    const models = [...new Set(rows.map(r => r.model_id || "preview"))];
    $("#prompt-model").innerHTML = models.map(m => `<option value="${safe(m)}">${safe(m === "preview" ? "Xem trước chung" : modelLabel(m))}</option>`).join("");
    if (preserve && models.includes(previousModel)) $("#prompt-model").value = previousModel;
    fillPromptPresets();
    if (preserve && previousRow) {
      const matching = rows.filter(r => (r.model_id || "preview") === $("#prompt-model").value);
      const index = matching.findIndex(r => r.preset_id === previousRow.preset_id);
      if (index >= 0) { $("#prompt-preset").value = String(index); fillPromptStages(); }
      if (stagesOf(promptRow() || {}).some(t => t.key === previousStage)) { $("#prompt-stage").value = previousStage; renderPromptDiff(); }
    }
  }
  function fillPromptPresets() {
    const rows = promptData.filter(r => (r.model_id || "preview") === $("#prompt-model").value);
    $("#prompt-preset").innerHTML = rows.map((r,i) => `<option value="${i}">${safe(r.preset_id?.toUpperCase() || "Tùy chỉnh")}</option>`).join("");
    fillPromptStages();
  }
  function promptRow() { return promptData.filter(r => (r.model_id || "preview") === $("#prompt-model").value)[Number($("#prompt-preset").value)]; }
  function fillPromptStages() {
    const row = promptRow();
    $("#prompt-stage").innerHTML = stagesOf(row || {}).map(t => `<option value="${safe(t.key)}">${safe(t.stage === "generate" ? "Sinh SQL" : t.stage === "c1" ? "C1 Phân rã" : t.stage === "c3" ? "C3 Kế hoạch" : "C4 Sửa lỗi")}${t.key.split(":")[1] !== "1" ? ` (lượt ${safe(t.key.split(":")[1])})` : ""}</option>`).join("");
    const generate = stagesOf(row || {}).find(t => t.stage === "generate");
    if (generate) $("#prompt-stage").value = generate.key;
    renderPromptDiff();
  }
  function messageText(stage) { return (stage?.messages || stage?.prompt || []).map(m => `[${m.role.toUpperCase()}]\n${m.content}`).join("\n\n"); }
  const diffView = { mode: matchMedia("(max-width: 760px)").matches ? "unified" : "split", changesOnly: true, openFolds: new Set(), key: "" };
  function diffOps(before, after) {
    const a = before.split("\n"), b = after.split("\n");
    if (a.length * b.length > 500000) return [...a.map((t, i) => ({ type: "remove", a: t, ai: i + 1 })), ...b.map((t, j) => ({ type: "add", b: t, bi: j + 1 }))];
    const grid = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
    for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) grid[i][j] = a[i] === b[j] ? grid[i + 1][j + 1] + 1 : Math.max(grid[i + 1][j], grid[i][j + 1]);
    const ops = []; let i = 0, j = 0;
    while (i < a.length || j < b.length) {
      if (i < a.length && j < b.length && a[i] === b[j]) { ops.push({ type: "same", a: a[i], b: b[j], ai: i + 1, bi: j + 1 }); i++; j++; }
      else if (i < a.length && (j === b.length || grid[i + 1][j] >= grid[i][j + 1])) { ops.push({ type: "remove", a: a[i], ai: i + 1 }); i++; }
      else { ops.push({ type: "add", b: b[j], bi: j + 1 }); j++; }
    }
    return ops;
  }
  function splitRows(ops) {
    const rows = []; let removed = [], added = [];
    const flush = () => { for (let k = 0; k < Math.max(removed.length, added.length); k++) rows.push({ type: "change", left: removed[k] || null, right: added[k] || null }); removed = []; added = []; };
    for (const op of ops) { if (op.type === "same") { flush(); rows.push({ type: "same", left: op, right: op }); } else if (op.type === "remove") removed.push(op); else added.push(op); }
    flush();
    return rows;
  }
  function foldRows(rows) {
    if (!diffView.changesOnly) return rows;
    const context = 2, out = []; let k = 0, foldId = 0;
    while (k < rows.length) {
      if (rows[k].type !== "same") { out.push(rows[k++]); continue; }
      let end = k; while (end < rows.length && rows[end].type === "same") end++;
      const run = rows.slice(k, end), head = k === 0 ? 0 : context, tail = end === rows.length ? 0 : context;
      const id = `f${foldId++}`;
      if (run.length > head + tail + 1 && !diffView.openFolds.has(id)) out.push(...run.slice(0, head), { type: "fold", id, count: run.length - head - tail }, ...run.slice(run.length - tail));
      else out.push(...run);
      k = end;
    }
    return out;
  }
  const roleLabels = { "[SYSTEM]": "System", "[USER]": "User", "[ASSISTANT]": "Assistant" };
  function diffCell(op, side) {
    if (!op) return '<div class="d-cell blank"></div>';
    const text = side === "left" ? op.a : op.b, line = side === "left" ? op.ai : op.bi;
    const mark = op.type === "add" ? "+" : op.type === "remove" ? "−" : "";
    if (roleLabels[text]) return `<div class="d-cell role ${op.type}"><span class="ln">${line}</span><span class="mk">${mark}</span><span class="tx">${roleLabels[text]}</span></div>`;
    return `<div class="d-cell ${op.type}"><span class="ln">${line}</span><span class="mk">${mark}</span><span class="tx">${safe(text) || " "}</span></div>`;
  }
  const foldButton = row => `<button type="button" class="d-fold" data-fold="${row.id}">${number(row.count)} dòng giống nhau, bấm để hiện</button>`;
  function renderDiffBody(before, after, leftLabel, rightLabel) {
    if (before === null) {
      const lines = after.split("\n");
      return `<div class="diff unified single">${lines.map((text, index) => diffCell({ type: "plain", b: text, bi: index + 1 }, "right")).join("")}</div>`;
    }
    const ops = diffOps(before, after);
    if (diffView.mode === "unified") {
      const rows = foldRows(ops.map(op => ({ type: op.type === "same" ? "same" : "change", op })));
      return `<div class="diff unified">${rows.map(row => row.type === "fold" ? foldButton(row) : diffCell(row.op, row.op.type === "remove" ? "left" : "right")).join("")}</div>`;
    }
    const rows = foldRows(splitRows(ops));
    return `<div class="diff split"><div class="d-head"><span>${safe(leftLabel)}</span><span>${safe(rightLabel)}</span></div>${rows.map(row => row.type === "fold" ? foldButton(row) : `<div class="d-row ${row.type}">${diffCell(row.left, "left")}${diffCell(row.right, "right")}</div>`).join("")}</div>`;
  }
  function syncPromptControls() {
    $("#prompt-preset-steps").innerHTML = [...$("#prompt-preset").options].map((option, index) => `${index ? '<span class="step-sep" aria-hidden="true">›</span>' : ""}<button type="button" data-index="${safe(option.value)}" aria-pressed="${option.value === $("#prompt-preset").value}">${safe(option.textContent)}</button>`).join("");
    $("#prompt-stage-tabs").innerHTML = [...$("#prompt-stage").options].map(option => `<button type="button" data-stage="${safe(option.value)}" aria-pressed="${option.value === $("#prompt-stage").value}">${safe(option.textContent)}</button>`).join("") || '<span class="tiny-note">Không có lượt gọi model.</span>';
    $$("[data-diff-mode]").forEach(button => { const active = button.dataset.diffMode === diffView.mode; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
  }
  function renderPromptRationale(row, previous, stage) {
    const host = $("#prompt-rationale");
    const isP2 = row.preset_id === "p2";
    const addedC2 = row.options?.c2 && previous && !previous.options?.c2;
    if (isP2 || addedC2) {
      const generation = stagesOf(row).find(t => t.stage === "generate");
      const messages = generation?.messages || row.messages || [];
      const examples = [];
      for (let i=0;i<messages.length-1;i++) {
        const content = messages[i].content || "";
        const marker = "\nCÂU HỎI: ";
        if (messages[i].role === "user" && content.startsWith("SCHEMA VÍ DỤ:\n") && content.includes(marker) && messages[i+1].role === "assistant") {
          let sql = ""; try { sql=JSON.parse(messages[i+1].content).sql || ""; } catch {}
          examples.push({question:content.slice(content.lastIndexOf(marker)+marker.length),sql});
        }
      }
      const tokens = text => new Set(String(text || "").toLowerCase().replace(/đ/g,"d").normalize("NFD").replace(/\p{M}/gu,"").split(/\s+/u).filter(Boolean));
      const target=tokens(promptSample?.question);
      const before=previous?.selected_tables, after=row.selected_tables || [];
      const removed=(before || []).filter(t=>!after.includes(t));
      const schemaReason = before ? (removed.length ? `Schema bớt ${removed.length} bảng: ${removed.join(", ")}. Giữ ${after.length}/${before.length} bảng để giảm ngữ cảnh không liên quan và giữ quan hệ JOIN cần thiết.` : `Schema vẫn giữ ${after.length}/${before.length} bảng. Ở mẫu này P2 không thu hẹp schema; phần bổ sung chính nằm ở các ví dụ train.`) : "Không có P1 trong dữ liệu đang xem để xác nhận schema đã thêm/bớt những bảng nào.";
      host.innerHTML=`<h3>Vì sao P1 → P2 bổ sung đoạn này?</h3><p><b>P1 bổ sung bước phân rã câu hỏi nhưng chưa cung cấp ví dụ cách chuyển yêu cầu thành SQL.</b> P2 bật C2: đưa các cặp câu hỏi–SQL từ train vào ngữ cảnh để model tham khảo cách dùng bảng/cột, JOIN, lọc và tổng hợp. Schema đi kèm mỗi ví dụ giúp phân biệt tên bảng/cột của ví dụ với database đang hỏi.</p><p><b>Schema của câu hỏi hiện tại:</b> ${safe(schemaReason)} Bộ liên kết hiện tại dựa trên từ khóa tên bảng/cột và đường khóa ngoại; đây là heuristic, có thể giữ thừa hoặc bỏ sót bảng.</p><h4>Vì sao chọn các ví dụ đang thấy trong prompt?</h4><p class="tiny-note">Triển khai C2 hiện tại xếp hạng theo Jaccard giữa các từ của câu hỏi sau chuẩn hóa tiếng Việt, chỉ lấy từ train và loại câu hỏi trùng target. Bộ hiện tại tách token theo khoảng trắng, giữ cả dấu câu và từ phổ biến. Từ trùng và điểm dưới đây được tính lại từ prompt đang xem; không phải xác suất SQL đúng. Không dùng SQL tham chiếu của mẫu đích để chọn ví dụ.</p>${examples.length ? examples.map((ex,i)=>{
        const candidate=tokens(ex.question), shared=[...target].filter(t=>candidate.has(t)).sort();
        const union=new Set([...target,...candidate]).size;
        const similarity=shared.length/Math.max(1,union);
        const patterns=[[/\bJOIN\b/i,"JOIN"],[/\bWHERE\b/i,"lọc WHERE"],[/\bGROUP\s+BY\b/i,"nhóm GROUP BY"],[/\bORDER\s+BY\b/i,"sắp xếp ORDER BY"],[/\bCOUNT\s*\(/i,"đếm COUNT"],[/\bAVG\s*\(/i,"trung bình AVG"],[/\bSUM\s*\(/i,"tổng SUM"],[/\bLIMIT\b/i,"giới hạn LIMIT"]].filter(([re])=>re.test(ex.sql)).map(([,name])=>name);
        return `<article class="rationale-example"><h4>Ví dụ ${i+1} · ${safe(row.example_ids?.[i] || "ID chưa lưu")} · Jaccard ${number(similarity,3)}</h4><p>${safe(ex.question)}</p><p><b>Căn cứ chọn:</b> ${shared.length}/${union} từ trong giao/hợp. Từ trùng: ${shared.length ? safe(shared.join(", ")) : "không có"}.</p><p><b>Đoạn SQL minh họa:</b> ${patterns.length ? safe(patterns.join(" · ")) : "cấu trúc SQL trong ví dụ bên dưới"}. Đây là nội dung ví dụ, chưa chứng minh nó phù hợp về ngữ nghĩa với câu hỏi hiện tại.</p>${!shared.length ? '<p class="tiny-note">Điểm bằng 0 nhưng bộ retrieval vẫn lấy đủ k ví dụ nếu có ứng viên; các trường hợp bằng điểm được sắp theo ID. Ví dụ này có thể không hữu ích.</p>' : ""}<details><summary>Xem SQL ví dụ thực sự được gửi</summary><pre>${safe(ex.sql || "Không đọc được SQL từ trace.")}</pre></details></article>`;
      }).join("") : '<p>Không có ví dụ được gửi trong lượt sinh SQL này (có thể k=0, không có ứng viên hoặc pipeline chưa tới bước sinh SQL). Không suy đoán ví dụ đã được dùng từ ID.</p>'}<p class="tiny-note"><b>Đánh đổi:</b> thêm ví dụ làm tăng input tokens; ví dụ gần nhau về từ có thể khác ý nghĩa. Điểm SQL phải được kiểm chứng bằng kết quả thực nghiệm, không suy ra từ việc prompt dài hơn.${stage?.stage === "c1" || stage?.stage === "c3" ? " Lượt gọi đang chọn chỉ nhận schema và nội dung lập kế hoạch; các ví dụ C2 nằm ở prompt Sinh SQL, không được đưa vào lượt gọi này." : ""}</p>`;
    } else {
      const calls=stagesOf(row), preview=row.kind === "preview";
      const generate=calls.find(t=>t.stage === "generate");
      const targetMessage=generate?.messages?.at(-1)?.content || "";
      const question=promptSample?.question || "Không có câu hỏi gốc trong dữ liệu đang xem.";
      const outputBlock=(title,call)=>call ? `<article class="rationale-example"><h4>${safe(title)}</h4><pre>${safe(call.output || call.error || "Chưa có phản hồi được lưu.")}</pre></article>` : '<p class="tiny-note">Chưa có đầu ra thực của bước này; không tạo nội dung minh họa thay cho model.</p>';
      const facts=`<p><b>Câu hỏi đang xét:</b> ${safe(question)}</p><p><b>Schema ban đầu:</b> ${safe((row.selected_tables || []).join(", ")) || "Chưa có thông tin"}.</p>`;
      const callInfo=preview ? '<p class="tiny-note">Đây là preview; số lượt gọi bên dưới là dự kiến, chưa có phản hồi hay điểm thực.</p>' : `<p class="tiny-note">Lượt gọi thực được lưu: ${calls.length}. ${numeric(row.metrics?.input_tokens) ? `Tổng input: ${number(row.metrics.input_tokens)} token.` : ""} Không gọi thêm model để viết phần giải thích này.</p>`;
      if (row.preset_id === "p0") {
        host.innerHTML=`<h3>Vì sao P0 cần prompt nền này?</h3><p>P0 là mốc đối chiếu: để model chuyển trực tiếp câu hỏi thành SQL bằng instruction và schema, trước khi thêm C1–C4. Mốc này giúp đo các phần bổ sung có ích hay chỉ tăng chi phí.</p>${facts}<div class="rationale-example"><h4>Vì sao có từng phần?</h4><ul><li><b>Instruction:</b> xác định nhiệm vụ Text-to-SQL tiếng Việt và yêu cầu một truy vấn SQLite chỉ đọc.</li><li><b>Schema/khóa:</b> cung cấp tên bảng, cột và quan hệ được phép dùng; giảm việc tự đoán tên.</li><li><b>Câu hỏi:</b> xác định thông tin, điều kiện và cách sắp xếp người dùng yêu cầu.</li><li><b>JSON sql/explanation và quy tắc quote:</b> giúp ứng dụng đọc đầu ra và xử lý tên tiếng Việt có khoảng trắng.</li></ul></div><p><b>Luồng:</b> câu hỏi + schema → sinh SQL → thực thi/đánh giá. Một lượt model nếu tới bước sinh SQL; không có ví dụ train, phân rã, kế hoạch hay lượt sửa.</p><p><b>Giới hạn:</b> model phải tự xử lý toàn bộ yêu cầu trong một lượt; SQL chạy được vẫn có thể sai ý.</p>${callInfo}`;
      } else if (row.preset_id === "p1") {
        const decomposition=calls.find(t=>t.stage === "c1");
        const injected=!preview && targetMessage.includes("CÂU HỎI CON:\n");
        let parts=[];
        try { parts=JSON.parse((decomposition?.output || "").replace(/^```[^\n]*\n/,"").replace(/```\s*$/,"" )).subquestions || []; } catch {}
        const sqlLike=Array.isArray(parts) && parts.some(x=>typeof x === "string" && /^\s*(SELECT|WITH)\b/i.test(x));
        host.innerHTML=`<h3>Vì sao P0 → P1 thêm câu hỏi con?</h3><p>P0 yêu cầu model sinh SQL ngay. P1 thêm C1 để tách câu hỏi thành tối đa bốn yêu cầu nhỏ, nhằm làm rõ các phần cần lọc, tổng hợp hoặc kết nối trước khi sinh SQL.</p>${facts}<p><b>Đoạn được thêm:</b> một prompt riêng yêu cầu JSON <code>subquestions</code>, sau đó khối <code>CÂU HỎI CON</code> được đưa vào cuối câu hỏi trong prompt Sinh SQL. Câu hỏi gốc và schema vẫn được giữ.</p><p><b>Luồng:</b> câu hỏi/schema → C1 phân rã → câu hỏi gốc + đầu ra C1 → Sinh SQL. Dự kiến hai lượt model nếu bước C1 thành công.</p>${preview ? '<p>Preview chỉ đặt placeholder cho C1; chưa có câu hỏi con thực để khẳng định đã được đưa vào prompt.</p>' : `<p><b>Bằng chứng ở run này:</b> ${decomposition ? "Có lượt gọi C1." : "Không thấy lượt gọi C1 trong trace."} ${Array.isArray(parts) && parts.length ? `Phản hồi đọc được ${parts.length} phần tử subquestions.` : "Chưa đọc được danh sách subquestions hợp lệ."} ${injected ? "Prompt Sinh SQL có khối CÂU HỎI CON." : "Chưa thấy khối CÂU HỎI CON trong prompt Sinh SQL được lưu; không suy đoán bước đã hoàn tất."}</p>${outputBlock("Đầu ra C1 thực được lưu",decomposition)}`}${sqlLike ? '<p><b>Quan sát:</b> có phần tử bắt đầu bằng SELECT/WITH. Model đang trả SQL ở nơi được yêu cầu câu hỏi con; JSON đọc được chưa chứng minh đã phân rã đúng.</p>' : ""}<p><b>Đánh đổi:</b> thêm một lượt gọi và input cho bước sau. Phân rã sai có thể làm SQL sai theo; không có bảo đảm P1 tốt hơn P0.</p>${callInfo}`;
      } else if (row.preset_id === "p3") {
        const plan=calls.find(t=>t.stage === "c3");
        const injected=!preview && targetMessage.includes("KẾ HOẠCH SQL:\n");
        host.innerHTML=`<h3>Vì sao P2 → P3 thêm kế hoạch SQL?</h3><p>P2 đã có phân rã và ví dụ train nhưng chưa có một bản tổ chức các thao tác SQL dành riêng cho câu hỏi hiện tại. P3 thêm C3 để yêu cầu model chỉ rõ bảng/cột, JOIN, lọc, nhóm và sắp xếp trước khi viết truy vấn cuối.</p>${facts}<p><b>Đoạn được thêm:</b> một prompt lập kế hoạch nhận schema đã chọn, câu hỏi và đầu ra C1. Phản hồi JSON được thêm thành khối <code>KẾ HOẠCH SQL</code> trong prompt Sinh SQL; C1 và các ví dụ C2 vẫn được giữ ở bước sinh.</p><p><b>Luồng:</b> C1 → C3 (câu hỏi + schema + phân rã) → Sinh SQL (thêm ví dụ C2 và kế hoạch). Dự kiến ba lượt model nếu các bước trước thành công. C3 không trực tiếp nhận các cặp ví dụ C2 trong triển khai hiện tại.</p>${preview ? '<p>Preview chỉ có placeholder cho kế hoạch; chưa có đầu ra C3 thực.</p>' : `<p><b>Bằng chứng ở run này:</b> ${plan ? "Có lượt gọi C3." : "Không thấy lượt gọi C3; pipeline có thể chưa tới bước này."} ${injected ? "Prompt Sinh SQL có khối KẾ HOẠCH SQL." : "Chưa thấy kế hoạch được chèn vào prompt Sinh SQL đã lưu."}</p>${outputBlock("Đầu ra C3 thực được lưu",plan)}` }<p><b>Đánh đổi:</b> tăng lượt gọi, token và thời gian; kế hoạch sai có thể hướng truy vấn đi sai. Đây là kế hoạch do model trả công khai theo yêu cầu, không phải suy luận nội bộ và không được coi là đúng chỉ vì là JSON.</p>${callInfo}`;
      } else if (row.preset_id === "p4") {
        const repairs=calls.filter(t=>t.stage === "repair");
        const executions=(row.trace || []).filter(t=>t.stage === "execute");
        const lastExecution=executions.at(-1)?.execution;
        const noRepairReason=preview ? "Chưa sinh hay thực thi SQL nên chưa biết có cần sửa hay không." : repairs.length ? `Có ${repairs.length} lượt sửa thực được lưu.` : !generate ? "Pipeline chưa có lượt Sinh SQL; không có căn cứ kết luận SQL đã chạy được." : lastExecution?.status === "ok" ? "SQL chạy được nên không kích hoạt sửa. Điều này chưa chứng minh SQL đúng với câu hỏi." : lastExecution?.status === "schema_only" ? "SQL qua kiểm tra schema-only nên không kích hoạt sửa; chưa có kết quả trên database có dữ liệu." : "Không có lượt sửa được lưu; kiểm tra lỗi/trạng thái pipeline và ngân sách sửa. Không suy ra rằng SQL đã thành công.";
        host.innerHTML=`<h3>Vì sao P3 → P4 thêm feedback thực thi?</h3><p>P3 có thực thi SQL để kiểm tra, nhưng không gọi model sửa khi có lỗi. P4 thêm C4 để dùng lỗi SQLite hoặc lỗi đọc đầu ra làm thông tin sửa cụ thể, thay vì yêu cầu model đoán lại mà không biết lỗi ở đâu.</p>${facts}<p><b>Đoạn được thêm khi có lỗi:</b> giữ hội thoại trước, bổ sung phản hồi assistant chứa SQL/đầu ra vừa sinh và một user message chứa lỗi cùng yêu cầu sửa câu hỏi gốc. System prompt dùng lại schema đầy đủ để model có cơ hội tìm bảng/cột bị bỏ sót.</p><p><b>Luồng:</b> C1 → C3 → Sinh SQL → thực thi → nếu lỗi thì sửa và thực thi lại. Dự kiến ba lượt ban đầu, thêm tối đa ${number(row.options?.max_repairs ?? 2)} lượt sửa; có thể dừng sớm nếu SQL lặp lại.</p><p><b>Vì sao có/không có đoạn sửa ở mẫu này?</b> ${safe(noRepairReason)}</p>${repairs.map((repair,i)=>{
          const feedback=[...(repair.messages || [])].reverse().find(m=>m.role === "user")?.content;
          return `<article class="rationale-example"><h4>Lượt sửa ${i+1} · feedback thực sự được gửi</h4><pre>${safe(feedback || "Không có user message được lưu; không dựng lại lỗi giả định.")}</pre>${outputBlock("Đầu ra model sau yêu cầu sửa",repair)}</article>`;
        }).join("")}<p><b>Kết quả sau xử lý:</b> ${preview ? "Chưa có kết quả thực." : row.status === "ok" ? "Pipeline báo thành công; xem EX/TS để phân biệt chạy được và trả lời đúng." : `Pipeline còn lỗi hoặc chưa hoàn tất: ${safe(row.error || row.status || "chưa rõ")}.`}</p><p><b>Giới hạn:</b> sửa có thể vẫn thất bại. SQL sai ý nhưng chạy được không tự được sửa bằng gold; không dùng đáp án tham chiếu để tạo feedback.</p>${callInfo}`;
      } else {
        host.innerHTML='<h3>Mục đích cấu hình</h3><p>Chọn P0–P4 để xem giải thích cho mức tương ứng, kèm bằng chứng từ prompt/trace đang xem.</p>';
      }
    }
  }
  function renderPromptDiff() {
    const row=promptRow(); if(!row) return;
    const rows=promptData.filter(r => (r.model_id || "preview") === $("#prompt-model").value);
    const index=rows.indexOf(row), previous=rows[index-1];
    const key=$("#prompt-stage").value;
    const stage=stagesOf(row).find(t=>t.key===key);
    let old=stagesOf(previous || {}).find(t=>t.key===key);
    let referenceLabel=previous?.preset_id?.toUpperCase() || "";
    if (stage?.stage === "repair") {
      const calls=stagesOf(row);old=calls[calls.findIndex(t=>t.key===key)-1];
      referenceLabel=`${row.preset_id?.toUpperCase() || "Tùy chỉnh"}, trước lượt sửa`;
    }
    const currentLabel=row.preset_id?.toUpperCase() || "Tùy chỉnh";
    const viewKey=`${$("#prompt-model").value}|${row.preset_id}|${key}`;
    if (diffView.key !== viewKey) { diffView.key = viewKey; diffView.openFolds.clear(); }
    const after=messageText(stage);
    const before=old ? messageText(old) : null;
    renderPromptRationale(row,previous,stage);
    syncPromptControls();
    const ops = before === null ? [] : diffOps(before, after);
    const added = ops.filter(op => op.type === "add").length, removed = ops.filter(op => op.type === "remove").length;
    const tokenNow = stage?.usage?.input_tokens, tokenBefore = old?.usage?.input_tokens;
    const tokenText = numeric(tokenNow) ? `<span class="pd-tokens">Input ${numeric(tokenBefore) ? `${number(tokenBefore)} → ` : ""}<b>${number(tokenNow)}</b> token${numeric(tokenBefore) ? ` (${tokenNow - tokenBefore >= 0 ? "+" : "−"}${number(Math.abs(tokenNow - tokenBefore))})` : ""}</span>` : "";
    const context = `Schema ban đầu: ${safe((row.selected_tables || []).join(", ")) || "chưa có"}. ${(row.example_ids || []).length} ví dụ train.${row.options?.c4 && !stagesOf(row).some(t=>t.stage==="repair") && !promptPreview ? " C4 không phát sinh lượt sửa." : ""}`;
    $("#prompt-summary").innerHTML = !stage ? '<p class="tiny-note">Cấu hình này chưa có lượt gọi model.</p>' : before === null
      ? `<p class="pd-line"><b>${safe(currentLabel)}</b> là mốc đầu tiên, chưa có cấu hình trước để so sánh. Dưới đây là toàn bộ prompt.${tokenText ? ` ${tokenText}` : ""}</p><p class="tiny-note">${context}</p>`
      : `<p class="pd-line"><b>${safe(currentLabel)}</b> so với <b>${safe(referenceLabel)}</b>${before === after ? '<span class="pd-same">Prompt không đổi</span>' : `<span class="pd-add">+${number(added)} dòng</span><span class="pd-rem">−${number(removed)} dòng</span>`}${tokenText}</p><p class="tiny-note">${context}</p>`;
    $(".prompt-toolbar").hidden = before === null || !stage;
    $("#prompt-diff").innerHTML = stage ? renderDiffBody(before, after, referenceLabel, currentLabel) : "";
    $("#prompt-response").textContent=pretty({output:stage?.output,error:stage?.error,usage:stage?.usage,duration_ms:stage?.duration_ms,prompt_hash:stage?.prompt_hash,stages:row.stages});
    renderLogMetricStrip();
  }
  async function previewPrompts() {
    if (!currentSample() || state.source !== "dataset" || state.previewBusy) return;
    const sampleId=currentSample().id; state.previewBusy=true;
    $("#prompt-preview-button").disabled=true;
    try { const data=await api("prompt-preview",{sample_id:sampleId});if(currentSample()?.id!==sampleId || state.source!=="dataset") return;$("#comparison-context").hidden=false;$("#comparison-context").innerHTML=`Xem trước prompt cho mẫu ${safe(data.sample.id)} (${safe(data.sample.db_id)})<br><span class="caption-detail">${safe(data.sample.question)}</span>`;setPromptData(data.results,true,data.sample);
      state.comparison=null;$("#compare-export").disabled=true;$("#gold-details").hidden=true;
      $("#compare-results").className="empty-state";
      $("#compare-results").innerHTML="<p>Đây là bản xem trước prompt. Bấm Chạy để nhận SQL và chỉ số thực.</p>";
    }
    catch(error) { notice($("#compare-status"),error.message,true); }
    finally {state.previewBusy=false;updateButtons();}
  }
  async function startSequence() {
    state.busy=true;updateButtons();sequenceDone=-1;
    $("#compare-loading").hidden=false;
    notice($("#compare-status"),"Đang tạo lượt chạy P0–P4 độc lập trên cùng mẫu dev…");
    try {
      const job=await api("benchmark",{split:"dev",sample_ids:[currentSample().id],model_ids:selected(".compare-model"),preset_ids:cumulativeIds});
      sequenceId=job.id;$("#sequence-cancel").hidden=false;
      pollSequence(job.id);
    } catch(error) { finishSequence();notice($("#compare-status"),error.message,true); }
  }
  function finishSequence() {state.busy=false;$("#compare-loading").hidden=true;$("#sequence-cancel").hidden=true;updateButtons();loadRuns();}
  async function pollSequence(id) {
    clearTimeout(sequenceTimer);
    try {
      const job=await api(`job?id=${encodeURIComponent(id)}`);
      notice($("#compare-status"),`P0–P4: ${job.done}/${job.total} kết quả · ${statusLabels[job.state] || job.state} · ${id}`);
      if(job.done>0 && sequenceDone!==job.done) {
        const run=await api(`export?id=${encodeURIComponent(id)}&format=json`);
        const record=run.records[0];
        renderComparison({id:run.id,sample:{id:record.sample_id,question:record.question,db_id:record.db_id},results:run.records});
        sequenceDone=job.done;
      }
      if(job.state!=="running") {finishSequence();if(job.error) notice($("#compare-status"),job.error,true);return;}
    } catch(error) {notice($("#compare-status"),`Chưa đọc được tiến độ: ${error.message}. Đang thử lại…`,true);}
    sequenceTimer=setTimeout(()=>pollSequence(id),2000);
  }
  async function reportRecords() {
    if(!state.job?.id) return;
    $("#report-details-button").disabled=true;
    try {
      const run=await api(`export?id=${encodeURIComponent(state.job.id)}&format=json`);
      state.reportDetailsId=run.id;
      $("#report-details-button").textContent=`Cập nhật từng mẫu & prompt (${run.done}/${run.total})`;
      $("#report-records").innerHTML=`<table><thead><tr><th>Mẫu / database</th><th>Model / preset</th><th>Trạng thái</th><th>EX / TS</th><th>SQL / lỗi</th><th>Prompt</th></tr></thead><tbody>${run.records.map((r,i)=>`<tr><td>${safe(r.sample_id)}<small>${safe(r.db_id)} · ${safe(r.difficulty)}</small></td><td>${safe(modelLabel(r.model_id))}<small>${safe(r.preset_id)}</small></td><td>${statusBadge(r.status)}</td><td>${score("ex",r.metrics.ex)} / ${score("ts",r.metrics.ts)}</td><td>${safe(r.sql)}<small>${safe(r.error || "")}</small></td><td><button class="button subtle small record-prompts" data-index="${i}">Xem</button></td></tr>`).join("")}</tbody></table>`;
      $$(".record-prompts").forEach(button=>button.addEventListener("click",()=>{
        const r=run.records[Number(button.dataset.index)];
        const rows=run.records.filter(x=>x.sample_id===r.sample_id).sort((a,b)=>a.model_id.localeCompare(b.model_id)||a.preset_id.localeCompare(b.preset_id));
        renderComparison({id:run.id,sample:{id:r.sample_id,question:r.question,db_id:r.db_id},results:rows});showView("compare");
        $("#prompt-model").value=r.model_id;fillPromptPresets();
        const list=rows.filter(x=>x.model_id===r.model_id);$("#prompt-preset").value=String(list.findIndex(x=>x.preset_id===r.preset_id));fillPromptStages();
        notice($("#compare-status"),`Kết quả đã lưu · ${r.sample_id} · ${r.question}`);
      }));
    } catch(error) {notice($("#benchmark-status"),error.message,true);}
    finally {$("#report-details-button").disabled=false;}
  }
  // ---------- Duyệt log ----------
  const logState = { runs: [], data: null, k: 1, chartPreset: null, timer: null, request: 0 };
  const seriesColors = ["#2f6bff", "#c2410c", "#0f766e", "#7c3aed", "#a16207"];
  const cellLabels = { pass: "EX đúng", fail: "EX sai", error: "Lỗi pipeline", na: "N/A", pending: "Chưa chạy" };
  const detailHome = { marker: null, results: null, prompt: null, mounted: false, saved: undefined };
  function logMetric() { return $("#log-metric").value; }
  function presetLabel(id) { return logState.data?.run.presets?.find(p => p.id === id)?.label || presets().find(p => p.id === id)?.label || id; }
  function mountDetail() {
    if (detailHome.mounted) return;
    if (!detailHome.marker) {
      detailHome.prompt = $("#prompt-inspector");
      detailHome.results = detailHome.prompt.previousElementSibling;
      detailHome.marker = document.createComment("compare-detail-home");
      detailHome.results.before(detailHome.marker);
    }
    detailHome.saved = state.comparison;
    $("#log-prompt").append(detailHome.prompt);
    $("#log-detail").append(detailHome.results);
    detailHome.mounted = true;
  }
  function unmountDetail() {
    if (!detailHome.mounted) return;
    detailHome.marker.after(detailHome.results, detailHome.prompt);
    detailHome.mounted = false;
    $("#log-metric-strip")?.remove();
    const saved = detailHome.saved;
    detailHome.saved = undefined;
    if (saved) { renderComparison(saved); return; }
    state.comparison = null;
    $("#comparison-context").hidden = true;
    $("#compare-export").disabled = true;
    $("#gold-details").hidden = true;
    $("#prompt-inspector").hidden = true;
    $("#compare-results").className = "empty-state";
    $("#compare-results").innerHTML = "<p>Chọn câu hỏi rồi bấm Chạy.</p>";
  }
  async function loadLogRuns(selectId) {
    try {
      const data = await api("runs");
      logState.runs = (data.runs || []).filter(run => (run.done || 0) > 0);
      const wanted = selectId || logState.data?.id || "";
      $("#log-run").innerHTML = '<option value="">Chọn lần chạy…</option>' + logState.runs.map(run => `<option value="${safe(run.id)}">${safe(run.id.slice(0, 8))} · ${run.purpose === "prompt_comparison" ? "Prompt" : "Benchmark"} · ${safe(run.split || "dev")} · ${number(run.done)}/${number(run.total)} kết quả · ${safe(run.created_at ? new Date(run.created_at).toLocaleString("vi-VN") : "")}</option>`).join("");
      if (wanted && !logState.runs.some(run => run.id === wanted)) $("#log-run").insertAdjacentHTML("beforeend", `<option value="${safe(wanted)}">${safe(wanted.slice(0, 8))}</option>`);
      $("#log-run").value = wanted;
      if (!logState.runs.length) notice($("#log-status"), "Chưa có lần chạy nào có kết quả.");
    } catch (error) { notice($("#log-status"), `Không thể tải danh sách lần chạy: ${error.message}`, true); }
  }
  async function openLog(id, { keepPosition = false } = {}) {
    clearTimeout(logState.timer);
    if (!id) { logState.data = null; $("#log-body").hidden = true; unmountDetail(); return; }
    const request = ++logState.request;
    if (!keepPosition) notice($("#log-status"), "Đang tải log…");
    try {
      const run = await api(`export?id=${encodeURIComponent(id)}&format=json`);
      if (request !== logState.request) return;
      const previous = logState.data?.id === id ? logState.data : null;
      const groups = RunLog.groupRecords(run);
      logState.data = { id, run, groups, done: run.done, steps: {} };
      const total = groups.questions.length;
      const followEnd = previous && logState.k === previous.groups.questions.length;
      logState.k = previous ? Math.min(followEnd ? total : logState.k, total) || 1 : 1;
      if (!logState.chartPreset || !groups.presets.includes(logState.chartPreset)) logState.chartPreset = groups.presets[0];
      $("#log-run").value = id;
      if (location.hash !== `#log/${id}` && !$("#view-log").hidden) history.replaceState(null, "", `#log/${id}`);
      const difficulties = [...new Set(groups.questions.map(q => q.difficulty).filter(Boolean))];
      const currentDifficulty = $("#log-difficulty").value;
      $("#log-difficulty").innerHTML = '<option value="">Mọi độ khó</option>' + difficulties.map(d => `<option value="${safe(d)}">${safe(d)}</option>`).join("");
      $("#log-difficulty").value = difficulties.includes(currentDifficulty) ? currentDifficulty : "";
      const running = ["running", "pending", "queued", "cancel_requested"].includes(run.state);
      notice($("#log-status"), `${statusLabels[run.state] || run.state} · ${number(run.done)}/${number(run.total)} kết quả · ${number(total)} câu · ${groups.models.length} mô hình × ${groups.presets.length} cấu hình${running ? " · đang tự cập nhật" : ""}`);
      $("#log-body").hidden = !total;
      if (!total) { notice($("#log-status"), "Lần chạy này chưa có kết quả."); return; }
      mountDetail();
      renderLog();
      if (running) logState.timer = setTimeout(() => watchLog(id), 4000);
    } catch (error) { if (request === logState.request) notice($("#log-status"), `Không thể tải log: ${error.message}`, true); }
  }
  async function watchLog(id) {
    if (logState.data?.id !== id) return;
    try {
      const job = await api(`job?id=${encodeURIComponent(id)}`);
      if (logState.data?.id !== id) return;
      if (job.done !== logState.data.done) { await openLog(id, { keepPosition: true }); return; }
      if (["running", "pending", "queued", "cancel_requested"].includes(job.state)) logState.timer = setTimeout(() => watchLog(id), 4000);
      else openLog(id, { keepPosition: true });
    } catch { logState.timer = setTimeout(() => watchLog(id), 8000); }
  }
  function logSteps(metric) {
    const data = logState.data;
    if (!data.steps[metric]) data.steps[metric] = RunLog.cumulative(data.groups, metric);
    return data.steps[metric];
  }
  function setLogK(k, { scroll = false } = {}) {
    const total = logState.data?.groups.questions.length || 0;
    if (!total) return;
    logState.k = Math.max(1, Math.min(total, k));
    renderLog();
    if (scroll) $("#log-body").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function formatDelta(metric, now, before) {
    if (!numeric(now) || !numeric(before)) return numeric(now) && before === null ? '<span class="delta">mới có</span>' : "";
    const diff = now - before;
    if (Math.abs(diff) < 1e-9) return '<span class="delta same">=</span>';
    const text = metric === "ves" ? number(Math.abs(diff), 3) : `${number(Math.abs(diff) * 100, 1)} đ`;
    return `<span class="delta ${diff > 0 ? "up" : "down"}">${diff > 0 ? "▲" : "▼"} ${text}</span>`;
  }
  function renderLog() {
    const data = logState.data;
    if (!data) return;
    const { groups } = data;
    const total = groups.questions.length;
    const k = logState.k;
    const question = groups.questions[k - 1];
    const metric = logMetric();
    const steps = logSteps(metric);
    $("#log-k").max = String(total);
    $("#log-k").value = String(k);
    $("#log-prev").disabled = k <= 1;
    $("#log-next").disabled = k >= total;
    $("#log-position").innerHTML = `Câu <b>${number(k)}</b>/${number(total)}`;
    $("#log-current").innerHTML = `<span class="log-current-meta">${safe(question.sample_id)} · ${safe(question.db_id)} · ${safe(question.difficulty)}</span>${safe(question.question)}`;
    renderLogChart(metric, steps);
    renderLogQuestions();
    const results = question.records;
    renderComparison({ id: data.id, sample: { id: question.sample_id, question: question.question, db_id: question.db_id }, results });
    renderLogMetricStrip();
    renderMetricDialog();
  }
  function renderLogMetricStrip() {
    if (!detailHome.mounted || !logState.data) return;
    const inspector = $("#prompt-inspector");
    let strip = $("#log-metric-strip");
    if (!strip) { strip = document.createElement("div"); strip.id = "log-metric-strip"; strip.className = "log-metric-strip"; }
    const controls = $(".prompt-controls", inspector);
    if (strip.previousElementSibling !== controls) controls.after(strip);
    const { groups } = logState.data;
    const k = logState.k, total = groups.questions.length;
    const question = groups.questions[k - 1];
    const model = $("#prompt-model").value;
    const preset = promptRow()?.preset_id;
    if (!groups.models.includes(model) || !groups.presets.includes(preset)) { strip.innerHTML = ""; return; }
    const record = question.records.find(r => r.model_id === model && r.preset_id === preset);
    const cards = scoreKeys.map(metric => {
      const steps = logSteps(metric);
      const cell = steps[k - 1][model][preset];
      const before = k > 1 ? steps[k - 2][model][preset].value : null;
      const own = record ? record.metrics?.[metric] : undefined;
      const ownText = record === undefined ? "chưa chạy" : own == null ? (record.status === "error" ? "lỗi" : "N/A") : score(metric, metricNumber(own));
      const ownClass = record === undefined ? "pending" : own == null ? (record.status === "error" ? "error" : "na") : metric === "ves" ? "" : Number(metricNumber(own)) >= 1 ? "pass" : "fail";
      const explained = true;
      const tag = explained ? "button" : "div";
      return `<${tag} class="metric-card${explained ? " explainable" : ""}"${explained ? ` type="button" data-explain="${metric}" title="Xem cách tính ${metric.toUpperCase()}"` : ""}><span class="metric-name">${metric.toUpperCase()}${explained ? ' <span class="explain-hint">Cách tính ⓘ</span>' : ""}</span><span class="metric-value${cell.value == null ? " na" : ""}">${cell.value == null ? "N/A" : score(metric, cell.value)}</span>${formatDelta(metric, cell.value, before)}<small>${number(cell.eligible)}/${number(cell.n)} đo được</small><small>câu này: <span class="own ${ownClass}">${safe(ownText)}</span></small></${tag}>`;
    }).join("");
    strip.innerHTML = `<p class="metric-strip-caption">Chỉ số cộng dồn sau <b>${number(k)}/${number(total)}</b> câu${k === total ? " (kết quả cuối)" : ""} · ${safe(modelLabel(model))} · ${safe(preset.toUpperCase())}</p><div class="metric-cards">${cards}</div>`;
  }
  const metricNames = { em: "EM", cm: "CM", ex: "EX", ts: "TS", ves: "VES" };
  const metricDefinitions = {
    em: "EM (Exact Set Match, theo bộ đánh giá Spider) so sánh <b>cấu trúc</b> SQL sinh ra với SQL tham chiếu. Cả hai được tách thành các thành phần SELECT, WHERE, GROUP BY, ORDER BY, AND/OR, INTERSECT/UNION/EXCEPT và từ khóa; giá trị hằng (chuỗi, số) bị bỏ qua, các mục được so dạng tập (không phụ thuộc thứ tự), cột nối qua khóa ngoại được coi là tương đương. EM = 1 chỉ khi <b>mọi</b> thành phần khớp hoàn toàn và tập bảng trong FROM giống nhau; ngược lại EM = 0.",
    cm: "CM (Component Matching) dùng <b>cùng cách tách với EM</b> nhưng cho điểm từng phần. Mỗi thành phần xuất hiện trong ít nhất một trong hai SQL được gọi là “đang hoạt động” và được chấm F1; với bộ Spider này F1 của một thành phần là 1 nếu khớp hoàn toàn, 0 nếu không. CM của một câu = trung bình F1 của các thành phần đang hoạt động (không có thành phần nào hoạt động thì CM = 1). SQL không biên dịch được → CM = 0.",
    ex: "EX (Execution Accuracy) <b>chạy</b> SQL sinh ra và SQL tham chiếu trên cùng database có dữ liệu (chế độ chỉ đọc, lấy toàn bộ kết quả), rồi so kết quả: phải cùng số cột, cùng số dòng và cùng giá trị. Nếu SQL tham chiếu có ORDER BY ở cấp ngoài cùng thì thứ tự dòng phải giống; nếu không, các dòng được so như một đa tập. Cho phép đổi thứ tự cột. SQL sinh ra lỗi hoặc vượt giới hạn → EX = 0. Database không qua kiểm tra (SQL tham chiếu chạy lỗi, thiếu dữ liệu…) → N/A.",
    ts: "TS (Test-suite Accuracy) giống EX nhưng chạy trên <b>nhiều phiên bản database</b> cùng schema, khác dữ liệu (bộ test-suite). TS = 1 chỉ khi kết quả khớp ở <b>mọi</b> phiên bản — để loại trường hợp SQL sai ý nhưng tình cờ ra đúng kết quả trên một database. Database chưa có ít nhất hai phiên bản dữ liệu khác nhau → N/A.",
    ves: "VES (Valid Efficiency Score) đo <b>tốc độ</b> của SQL đúng. Chỉ tính khi EX đo được: EX = 0 thì VES = 0. Khi EX = 1, SQL tham chiếu và SQL sinh ra được chạy xen kẽ 100 lần trên database; mỗi cặp lấy √(thời gian SQL tham chiếu / thời gian SQL sinh ra), VES của câu là trung bình các tỉ lệ này. VES > 1 nghĩa là SQL sinh ra chạy nhanh hơn SQL tham chiếu.",
  };
  const emComponentNames = {
    "select": "SELECT (cột + hàm gộp)", "select(no AGG)": "SELECT (bỏ qua hàm gộp)",
    "where": "WHERE (điều kiện + toán tử)", "where(no OP)": "WHERE (bỏ qua toán tử)",
    "group(no Having)": "GROUP BY", "group": "GROUP BY + HAVING", "order": "ORDER BY (+ có/không LIMIT)",
    "and/or": "AND / OR", "IUEN": "INTERSECT / UNION / EXCEPT", "keywords": "Từ khóa SQL dùng",
  };
  const passMark = '<span class="own pass">✓</span>', failMark = '<span class="own fail">✗</span>';
  function reasonText(reason) {
    reason = String(reason || "");
    if (/^Valid SQL unsupported by Spider adapter/.test(reason)) return "SQL sinh ra hợp lệ nhưng bộ phân tích Spider không đọc được cấu trúc này";
    if (/^Gold SQL unsupported by Spider adapter/.test(reason)) return "SQL tham chiếu không phân tích được bằng bộ Spider";
    if (/^No gold SQL/.test(reason)) return "Không có SQL tham chiếu";
    if (/^Gold SQL execution audit failed/.test(reason)) return "Database không qua kiểm tra: có SQL tham chiếu của database này chạy lỗi";
    if (/^Gold full execution unavailable/.test(reason)) return "SQL tham chiếu không chạy trọn vẹn được";
    if (/^Compatible data-filled SQLite database unavailable/.test(reason)) return "Không có database có dữ liệu cho câu này";
    if (/At least two distinct test-suite states/.test(reason)) return "Database này chưa có ít nhất hai phiên bản dữ liệu test-suite";
    if (/^Test-suite schema\/data\/gold audit failed/.test(reason)) return "Một phiên bản test-suite không qua kiểm tra";
    if (/^VES requires/.test(reason)) return "VES cần EX đo được và SQL tham chiếu hợp lệ";
    if (/^VES repeated|^VES repetition|^VES timings/.test(reason)) return "Không hoàn tất đủ các lượt đo thời gian";
    return reason || "Không có lý do được lưu";
  }
  const continuous = metric => metric === "cm" || metric === "ves";
  function breakdownFormula(metric, b) {
    const name = metricNames[metric];
    if (!b.eligible) return `${name} = N/A (chưa có câu nào đo được)`;
    return continuous(metric)
      ? `${name} = tổng điểm các câu / số câu đo được = <b>${number(b.sum, 3)} / ${number(b.eligible)}</b> = <b>${score(metric, b.value)}</b>`
      : `${name} = số câu đạt (= 1) / số câu đo được = <b>${number(b.ones)} / ${number(b.eligible)}</b> = <b>${score(metric, b.value)}</b>`;
  }
  function breakdownDetails(metric, b) {
    const name = metricNames[metric];
    const grouped = {};
    for (const [reason, count] of Object.entries(b.naReasons)) grouped[reasonText(reason)] = (grouped[reasonText(reason)] || 0) + count;
    const reasons = Object.entries(grouped).sort((a, c) => c[1] - a[1]).map(([reason, count]) => `<li>${number(count)} câu: ${safe(reason)}</li>`).join("");
    const partial = b.eligible - b.ones - b.zeros;
    const split = metric === "ves"
      ? `<span class="own fail">${number(b.zeros)} câu VES = 0 (EX = 0)</span> · <span class="own pass">${number(b.eligible - b.zeros)} câu có VES &gt; 0</span>`
      : `<span class="own pass">${number(b.ones)} câu ${name} = 1</span> · <span class="own fail">${number(b.zeros)} câu ${name} = 0</span>${partial > 0 ? ` · ${number(partial)} câu điểm lẻ` : ""}`;
    return `<ul class="em-counts"><li>${number(b.n)} câu đã chạy với cấu hình này</li><li>${split} → ${number(b.eligible)} câu đo được (mẫu số)</li>${b.na ? `<li>${number(b.na)} câu N/A, không tính vào mẫu số:<ul>${reasons}</ul></li>` : ""}</ul>`;
  }
  function chipClass(metric, value) {
    if (value === undefined) return "pending";
    if (value === null) return "na";
    if (metric === "ves") return value > 0 ? "pass" : "fail";
    return value >= 1 ? "pass" : value <= 0 ? "fail" : "partial";
  }
  function storedVerdict(metric, record) {
    const name = metricNames[metric];
    if (!record) return "Cấu hình này chưa chạy câu này.";
    const m = record.metrics || {};
    const raw = m[metric];
    if (raw == null) return `${name} = N/A: ${safe(reasonText(m.unavailable_reasons?.[metric] || (record.status === "error" ? "Lỗi pipeline" : "")))}. Câu này không được tính vào mẫu số.`;
    const value = Number(metricNumber(raw));
    if (metric === "em" || metric === "cm") {
      const ex = RunLog.explainEm(record);
      if (ex.status === "invalid") return `SQL sinh ra không biên dịch được với schema (hoặc pipeline lỗi), nên được tính là dự đoán sai: <b>${name} = 0</b>.`;
      if (metric === "cm") {
        const active = ex.components.filter(c => c.active), matched = active.filter(c => c.match);
        return active.length ? `${number(matched.length)}/${number(active.length)} thành phần đang hoạt động khớp → <b>CM = ${number(matched.length)} / ${number(active.length)} = ${score("cm", value)}</b>.` : "Không có thành phần nào hoạt động → <b>CM = 1</b>.";
      }
      if (ex.status === "match") return "Mọi thành phần đều khớp và tập bảng trong FROM giống nhau → <b>EM = 1</b>.";
      return ex.tableMismatch ? "Các thành phần đều khớp nhưng tập bảng trong FROM khác SQL tham chiếu → <b>EM = 0</b>." : `Thành phần không khớp: <b>${ex.failed.map(key => safe(emComponentNames[key] || key)).join(", ")}</b> → <b>EM = 0</b>.`;
    }
    if (metric === "ex") return value >= 1 ? "Kết quả hai SQL giống nhau → <b>EX = 1</b>." : m.execution_success === false ? "SQL sinh ra không chạy trọn vẹn được → <b>EX = 0</b>." : "Kết quả hai SQL khác nhau → <b>EX = 0</b>.";
    if (metric === "ts") {
      const states = m.ts_details?.evaluated_states;
      return value >= 1 ? `Kết quả khớp ở cả ${number(states)} phiên bản database → <b>TS = 1</b>.` : `Kết quả không khớp ở ít nhất một trong ${number(states)} phiên bản database → <b>TS = 0</b>.`;
    }
    const d = m.ves_details || {};
    if (Number(metricNumber(m.ex)) < 1) return "EX = 0 nên <b>VES = 0</b> (không đo thời gian cho SQL sai).";
    return `VES = trung bình √(t<sub>tham chiếu</sub> / t<sub>sinh ra</sub>) trên ${number(d.completed_pairs)} cặp chạy = <b>${score("ves", value)}</b>. Thời gian trung bình: SQL tham chiếu ${duration(d.gold_mean_sql_ms)}, SQL sinh ra ${duration(d.prediction_mean_sql_ms)}. Lưu ý: không lấy √(trung bình gold / trung bình sinh ra) vì vài lượt chạy chậm bất thường sẽ kéo lệch trung bình; VES lấy trung bình của tỉ lệ từng cặp.`;
  }
  function renderMetricDialog() {
    const dialog = $("#metric-dialog");
    const info = logState.dialog;
    if (!dialog.open || !info || !logState.data) return;
    const { metric } = info;
    const name = metricNames[metric];
    const { groups } = logState.data;
    const k = logState.k, total = groups.questions.length;
    const question = groups.questions[k - 1];
    const record = question.records.find(r => r.model_id === info.model && r.preset_id === info.preset);
    const now = RunLog.metricBreakdown(groups, metric, info.model, info.preset, k);
    const final = RunLog.metricBreakdown(groups, metric, info.model, info.preset, total);
    $("#metric-dialog-title").innerHTML = `Cách tính ${name} <span class="caption-detail">${safe(modelLabel(info.model))} · ${safe(info.preset.toUpperCase())}</span>`;
    $("#metric-tabs").innerHTML = Object.keys(metricNames).map(key => `<button type="button" data-metric="${key}" aria-pressed="${key === metric}">${metricNames[key]}</button>`).join("");
    const own = record ? record.metrics?.[metric] : undefined;
    const chips = groups.questions.map((q, index) => {
      const item = final.perQuestion[index];
      const label = item.value === undefined ? "chưa chạy" : item.value === null ? "N/A" : score(metric, item.value);
      return `<button type="button" class="em-chip ${chipClass(metric, item.value)}${index + 1 > k ? " later" : ""}${index + 1 === k ? " current" : ""}" data-k="${index + 1}" title="Câu ${index + 1} · ${safe(q.sample_id)} · ${name} ${label}">${index + 1}</button>`;
    }).join("");
    $("#metric-dialog-body").innerHTML = `
      <section><h3>${name} là gì?</h3><p>${metricDefinitions[metric]}</p></section>
      <section><h3>Ở câu này <span class="caption-detail">câu ${number(k)}/${number(total)} · ${safe(question.sample_id)} · ${name} = ${record === undefined ? "chưa chạy" : own == null ? "N/A" : score(metric, metricNumber(own))}</span></h3><p class="em-question">${safe(question.question)}</p><div id="metric-detail" data-key="${safe(record ? `${metric}|${question.sample_id}|${record.model_id}|${record.preset_id}` : "")}">${record?.sql ? '<p class="tiny-note">Đang phân tích chi tiết…</p>' : record ? '<p class="tiny-note">Không có SQL sinh ra để phân tích.</p>' : ""}</div><p class="em-verdict">${storedVerdict(metric, record)}</p></section>
      <section><h3>Cộng dồn từ câu 1 đến câu ${number(k)}</h3><p>${breakdownFormula(metric, now)}</p>${breakdownDetails(metric, now)}</section>
      <section><h3>Toàn bộ benchmark (${number(total)} câu)</h3><p>${breakdownFormula(metric, final)}</p>${breakdownDetails(metric, final)}<p class="tiny-note">Đây là con số trong bảng Báo cáo. Ô màu: xanh = ${metric === "ves" ? "VES &gt; 0" : "1"}, đỏ = 0${metric === "cm" ? ", vàng = điểm lẻ" : ""}, xám = N/A; các câu sau câu đang xem được làm mờ. Bấm một ô để chuyển tới câu đó.</p><div class="em-chips">${chips}</div></section>`;
    loadMetricDetail();
  }
  const explainCache = new Map();
  function sqlPair(title, gold, pred) {
    return `<div class="em-step"><p class="em-step-title">${title}</p><div class="em-pair"><div><p class="detail-label">SQL tham chiếu (câu gốc)</p><div class="sql-block"><pre>${safe(gold || "—")}</pre></div></div><div><p class="detail-label">SQL sinh ra</p><div class="sql-block"><pre>${safe(pred || "—")}</pre></div></div></div></div>`;
  }
  function itemList(items) {
    if (items == null) return '<span class="na">không tách được</span>';
    return items.length ? items.map(item => `<code>${safe(item)}</code>`).join(" ") : '<span class="na">—</span>';
  }
  function renderStructure(data, metric) {
    const { gold, pred } = data;
    const tokens = { ...gold.tokens, ...pred.tokens };
    const legend = Object.entries(tokens).sort((a, b) => Number(a[0].slice(1)) - Number(b[0].slice(1))).map(([token, name]) => `<span><code>${safe(token)}</code> = ${safe(name)}</span>`).join("");
    const errors = ["gold", "pred"].filter(side => data[side].error).map(side => `<p class="result-error">${side === "gold" ? "SQL tham chiếu" : "SQL sinh ra"} không tách được: ${safe(data[side].error)}</p>`).join("");
    const rows = data.comparison.length ? data.comparison : Object.keys(gold.components || pred.components || {}).map(key => ({ key, match: null }));
    const cm = metric === "cm";
    const sameTables = gold.tables && pred.tables ? JSON.stringify(gold.tables) === JSON.stringify(pred.tables) : null;
    const head = `<tr><th>Thành phần</th><th>SQL tham chiếu</th><th>SQL sinh ra</th>${cm ? '<th class="num">Đang hoạt động</th><th class="num">F1</th>' : '<th class="num">Khớp</th>'}</tr>`;
    const compRows = rows.map(row => {
      const active = row.gold_total || row.pred_total;
      const cells = cm ? `<td class="num">${row.match == null ? "—" : active ? "có" : '<span class="na">không</span>'}</td><td class="num">${row.match == null ? "—" : active ? (row.match ? '<span class="own pass">1</span>' : '<span class="own fail">0</span>') : '<span class="na">bỏ qua</span>'}</td>` : `<td class="num">${row.match == null ? "—" : row.match ? passMark : failMark}</td>`;
      return `<tr class="${row.match === false && (!cm || active) ? "miss" : ""}${cm && row.match != null && !active ? " idle" : ""}"><td>${safe(emComponentNames[row.key] || row.key)}${cm && row.key === "and/or" ? "<small>Spider luôn tính thành phần này là đang hoạt động</small>" : ""}</td><td>${itemList(gold.components?.[row.key])}</td><td>${itemList(pred.components?.[row.key])}</td>${cells}</tr>`;
    }).join("");
    const tableRow = cm ? "" : `<tr class="${sameTables === false ? "miss" : ""}"><td>Tập bảng trong FROM<small>chỉ kiểm khi mọi thành phần đã khớp</small></td><td>${itemList(gold.tables)}</td><td>${itemList(pred.tables)}</td><td class="num">${sameTables == null ? "—" : sameTables ? passMark : failMark}</td></tr>`;
    const activeRows = rows.filter(row => row.gold_total || row.pred_total), matched = activeRows.filter(row => row.match);
    const cmLine = cm && data.comparison.length ? `<p>CM = ${number(matched.length)} thành phần khớp / ${number(activeRows.length)} thành phần đang hoạt động = <b>${activeRows.length ? score("cm", matched.length / activeRows.length) : score("cm", 1)}</b>.</p>` : "";
    return `${sqlPair("Bước 1. Hai câu SQL được so", data.gold_sql, data.pred_sql)}
      <div class="em-step"><p class="em-step-title">Bước 2. Đổi tên bảng/cột tiếng Việt thành mã</p><p class="tiny-note">Bộ phân tích Spider chỉ đọc được tên không dấu, không khoảng trắng, nên mỗi tên bảng/cột trong schema được thay bằng mã <code>u0, u1, …</code> (hàm <code>_rewrite</code>); alias như <code>t1</code>, <code>k</code> được giữ, chuỗi hằng không bị đổi.</p><div class="em-pair"><div><div class="sql-block"><pre>${safe(gold.canonical_sql || "—")}</pre></div></div><div><div class="sql-block"><pre>${safe(pred.canonical_sql || "—")}</pre></div></div></div><p class="em-legend">${legend}</p></div>
      <div class="em-step"><p class="em-step-title">Bước 3. Tách thành cây cấu trúc bằng Spider <code>process_sql.get_sql</code></p><p class="tiny-note">Dùng bộ phân tích gốc của benchmark Spider (đặt trong <code>text2sql_demo/experiment/vendor/spider</code>). Sau khi tách: giá trị hằng bị bỏ (hiện là <code>?</code>), alias được quy về tên bảng, và các cột nối với nhau qua khóa ngoại được quy về một cột đại diện — nên một cột có thể hiện dưới tên bảng khác với trong SQL.</p>${errors}</div>
      <div class="em-step"><p class="em-step-title">Bước 4. ${cm ? "Chấm F1 từng thành phần đang hoạt động" : "So từng thành phần (dạng tập, không xét thứ tự)"}</p><table class="em-components"><thead>${head}</thead><tbody>${compRows}${tableRow}</tbody></table>${cmLine}</div>`;
  }
  function resultTable(view, title) {
    if (!view) return `<div><p class="detail-label">${title}</p><p class="na">Không chạy.</p></div>`;
    const rows = view.rows.map(row => `<tr>${row.map(cell => `<td>${safe(cell === null ? "NULL" : cell)}</td>`).join("")}</tr>`).join("");
    return `<div><p class="detail-label">${title} <span class="muted">· ${number(view.row_count)} dòng × ${number(view.columns.length)} cột · ${duration(view.duration_ms)}</span></p>${view.error ? `<p class="result-error">${safe(view.error)}</p>` : ""}<div class="result-preview"><table><thead><tr>${view.columns.map(c => `<th>${safe(c)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>${view.row_count > view.rows.length ? `<p class="tiny-note">Chỉ hiện ${number(view.rows.length)} dòng đầu.</p>` : ""}</div></div>`;
  }
  function renderExecution(data, metric) {
    const pred = data.pred, gold = data.gold;
    const steps = [];
    if (gold && pred) {
      let stop = false;
      const step = (label, detail, ok) => {
        const shown = stop ? null : ok;
        steps.push(`<tr class="${shown === false ? "miss" : ""}"><td>${label}</td><td>${detail}</td><td class="num">${shown == null ? '<span class="na">không xét</span>' : shown ? passMark : failMark}</td></tr>`);
        if (ok === false) stop = true;
      };
      step("SQL sinh ra chạy trọn vẹn", pred.complete ? "chạy xong, lấy đủ kết quả" : safe(pred.error || pred.status), pred.complete);
      step("Số cột", `${number(gold.columns.length)} (tham chiếu) và ${number(pred.columns.length)} (sinh ra)`, gold.columns.length === pred.columns.length);
      step("Số dòng", `${number(gold.row_count)} và ${number(pred.row_count)}`, gold.row_count === pred.row_count);
      step("Giá trị", data.ordered ? "SQL tham chiếu có ORDER BY ngoài cùng → so đúng thứ tự dòng; cho phép đổi thứ tự cột" : "Không có ORDER BY ngoài cùng → so như đa tập (không xét thứ tự dòng); cho phép đổi thứ tự cột", data.verdict === "match" || data.verdict === "match_permuted");
    }
    const verdictText = { match: "Hai kết quả giống nhau → EX = 1.", match_permuted: "Hai kết quả giống nhau sau khi đổi thứ tự cột → EX = 1.", column_count: "Khác số cột → EX = 0.", row_count: "Khác số dòng → EX = 0.", values: "Cùng kích thước nhưng khác giá trị → EX = 0.", pred_error: "SQL sinh ra chạy lỗi → EX = 0.", pred_bounded: "SQL sinh ra vượt giới hạn thời gian/kích thước → EX = 0." }[data.verdict];
    const vesNote = metric === "ves" ? '<p class="tiny-note">VES dùng chính phép so khớp này (EX). Thời gian ở đây chỉ là một lần chạy lại để minh họa; điểm VES dùng các cặp chạy đã đo lúc benchmark, xem dòng kết luận bên dưới.</p>' : "";
    return `${sqlPair("Bước 1. Hai câu SQL được chạy", data.gold_sql, data.pred_sql)}
      <div class="em-step"><p class="em-step-title">Bước 2. Chạy cả hai trên database <code>${safe(data.db_id)}</code> (chỉ đọc, lấy toàn bộ kết quả)</p>${data.available ? "" : `<p class="tiny-note">Không chấm được: ${safe(reasonText(data.reason))}.</p>`}<div class="em-pair">${resultTable(gold, "Kết quả SQL tham chiếu")}${resultTable(pred, "Kết quả SQL sinh ra")}</div></div>
      ${data.available ? `<div class="em-step"><p class="em-step-title">Bước 3. So hai kết quả (dừng ở bước đầu tiên không khớp)</p><table class="em-components"><thead><tr><th>Kiểm tra</th><th>Chi tiết</th><th class="num">Đạt</th></tr></thead><tbody>${steps.join("")}</tbody></table>${verdictText ? `<p>Lần chạy lại này: <b>${verdictText}</b></p>` : ""}${vesNote}</div>` : ""}`;
  }
  function renderTestSuite(data) {
    if (!data.available) return `${sqlPair("Hai câu SQL được chạy", data.gold_sql, data.pred_sql)}<p class="tiny-note">Không chấm TS được: ${safe(reasonText(data.reason))}.</p>`;
    const matched = data.states.filter(s => s.match).length;
    const preview = rows => safe(rows.map(row => row.join(", ")).join(" | ") || "(rỗng)");
    const why = { column_count: "khác số cột", row_count: "khác số dòng", values: "khác giá trị", pred_error: "SQL lỗi", pred_bounded: "vượt giới hạn" };
    const rows = data.states.map((s, i) => `<tr class="${s.match ? "" : "miss"}"><td>${i + 1}. <code>${safe(s.name)}</code></td><td class="num" title="${preview(s.gold_preview)}">${number(s.gold_rows)}</td><td class="num" title="${preview(s.pred_preview)}">${number(s.pred_rows)}</td><td>${s.match ? passMark : `${failMark} <small>${safe(why[s.verdict] || s.verdict)}</small>`}</td></tr>`).join("");
    return `${sqlPair("Bước 1. Hai câu SQL được chạy", data.gold_sql, data.pred_sql)}
      <div class="em-step"><p class="em-step-title">Bước 2. Chạy trên ${number(data.states.length)} phiên bản database của <code>${safe(data.db_id)}</code> và so như EX ở từng phiên bản</p><p class="tiny-note">Mỗi phiên bản có cùng schema nhưng dữ liệu khác. Di chuột vào số dòng để xem vài dòng đầu của kết quả.</p><div class="result-preview tall"><table class="em-components"><thead><tr><th>Phiên bản database</th><th class="num">Dòng (tham chiếu)</th><th class="num">Dòng (sinh ra)</th><th>Khớp</th></tr></thead><tbody>${rows}</tbody></table></div><p>${number(matched)}/${number(data.states.length)} phiên bản khớp → lần chạy lại này: <b>TS = ${data.ts}</b>.</p></div>`;
  }
  async function loadMetricDetail() {
    const host = $("#metric-detail");
    if (!host?.dataset.key) return;
    const key = host.dataset.key;
    const [metric, sampleId, model, preset] = key.split("|");
    const record = logState.data?.groups.questions.find(q => q.sample_id === sampleId)?.records.find(r => r.model_id === model && r.preset_id === preset);
    if (!record?.sql) return;
    const kind = metric === "em" || metric === "cm" ? "em" : metric === "ts" ? "ts" : "ex";
    const cacheKey = `${kind}|${sampleId}|${model}|${preset}`;
    try {
      if (!explainCache.has(cacheKey)) explainCache.set(cacheKey, api("metric-explain", { sample_id: sampleId, sql: record.sql, metric: kind }));
      const data = await explainCache.get(cacheKey);
      if ($("#metric-detail")?.dataset.key !== key) return;
      host.innerHTML = kind === "em" ? renderStructure(data, metric) : kind === "ts" ? renderTestSuite(data) : renderExecution(data, metric);
    } catch (error) {
      explainCache.delete(cacheKey);
      if ($("#metric-detail")?.dataset.key !== key) return;
      host.innerHTML = `<p class="detail-label">SQL sinh ra</p><div class="sql-block"><pre>${safe(record.sql)}</pre></div><p class="tiny-note">Không lấy được phân tích chi tiết: ${safe(error.message)}. Kết luận bên dưới dựa trên số liệu đã lưu trong log.</p>`;
    }
  }
  function openMetricDialog(metric) {
    const model = $("#prompt-model").value, preset = promptRow()?.preset_id;
    if (!logState.data || !preset) return;
    logState.dialog = { metric, model, preset };
    const dialog = $("#metric-dialog");
    if (!dialog.open) dialog.showModal();
    renderMetricDialog();
  }
  function metricNumber(value) { return value === true ? 1 : value === false ? 0 : value; }
  function renderLogChart(metric, steps) {
    const { groups } = logState.data;
    const preset = logState.chartPreset;
    $("#log-chart-presets").innerHTML = groups.presets.map(id => `<button type="button" data-preset="${safe(id)}" aria-pressed="${id === preset}" title="${safe(presetLabel(id))}">${safe(id.toUpperCase())}</button>`).join("");
    $("#log-chart-caption").innerHTML = `Hình A. ${metric.toUpperCase()} cộng dồn theo thứ tự câu, cấu hình ${safe(preset.toUpperCase())}<br><span class="caption-detail">Mỗi đường là một mô hình; vạch dọc là câu đang xem. Bấm vào biểu đồ để nhảy tới câu.</span>`;
    const total = steps.length;
    const W = 760, H = 260, L = 48, R = 16, T = 14, B = 34;
    const values = steps.flatMap(step => groups.models.map(model => step[model][preset].value)).filter(numeric);
    const maxY = metric === "ves" ? Math.max(1.2, ...values) * 1.05 : 1;
    const x = i => L + (total === 1 ? (W - L - R) / 2 : (i / (total - 1)) * (W - L - R));
    const y = v => T + (1 - v / maxY) * (H - T - B);
    const ticks = metric === "ves" ? [0, maxY / 2, maxY].map(v => Math.round(v * 100) / 100) : [0, 0.25, 0.5, 0.75, 1];
    const xTicks = [...new Set([1, Math.round(total / 4), Math.round(total / 2), Math.round(3 * total / 4), total].filter(v => v >= 1))];
    const grid = ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${metric === "ves" ? v : `${Math.round(v * 100)}%`}</text>`).join("")
      + xTicks.map(v => `<text x="${x(v - 1)}" y="${H - 12}" text-anchor="middle">${v}</text>`).join("");
    const lines = groups.models.map((model, index) => {
      let d = "", pen = false;
      steps.forEach((step, i) => {
        const v = step[model][preset].value;
        if (!numeric(v)) { pen = false; return; }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      });
      const current = steps[logState.k - 1][model][preset].value;
      const color = seriesColors[index % seriesColors.length];
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>${numeric(current) ? `<circle cx="${x(logState.k - 1)}" cy="${y(current)}" r="4" fill="${color}" stroke="#fff" stroke-width="1.5"><title>${safe(modelLabel(model))}: ${score(metric, current)}</title></circle>` : ""}`;
    }).join("");
    const marker = `<line x1="${x(logState.k - 1)}" x2="${x(logState.k - 1)}" y1="${T}" y2="${H - B}" class="marker"/>`;
    const legend = groups.models.map((model, index) => {
      const v = steps[logState.k - 1][model][preset].value;
      return `<span class="legend-item"><svg class="swatch" viewBox="0 0 14 4" aria-hidden="true"><rect width="14" height="4" rx="2" fill="${seriesColors[index % seriesColors.length]}"/></svg>${safe(modelLabel(model))} <b>${v == null ? "N/A" : score(metric, v)}</b></span>`;
    }).join("");
    $("#log-chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${safe(metric.toUpperCase())} cộng dồn theo câu">${grid}${marker}${lines}<text x="${(L + W - R) / 2}" y="${H}" text-anchor="middle" class="axis-title">Số câu đã tính</text></svg><div class="chart-legend">${legend}</div>`;
    const svg = $("#log-chart svg");
    svg.addEventListener("click", event => {
      const box = svg.getBoundingClientRect();
      const px = (event.clientX - box.left) / box.width * W;
      const i = total === 1 ? 0 : Math.round((px - L) / (W - L - R) * (total - 1));
      setLogK(i + 1);
    });
  }
  function renderLogQuestions() {
    const { groups } = logState.data;
    const shown = RunLog.filterQuestions(groups.questions, { difficulty: $("#log-difficulty").value, onlyProblems: $("#log-problems").checked });
    $("#log-question-count").textContent = `(${number(shown.length)}/${number(groups.questions.length)} câu)`;
    const current = groups.questions[logState.k - 1]?.sample_id;
    if (!shown.length) { $("#log-questions").innerHTML = '<p class="empty-line">Không có câu phù hợp bộ lọc.</p>'; return; }
    const header = `<div class="ex-grid-head">${groups.presets.map(p => `<span title="${safe(presetLabel(p))}">${safe(p.toUpperCase())}</span>`).join("")}</div>`;
    $("#log-questions").innerHTML = `<table><thead><tr><th scope="col">#</th><th scope="col">Câu hỏi</th><th scope="col">${header}</th><th scope="col" class="num">Sai/lỗi</th></tr></thead><tbody>${shown.map(q => {
      const index = groups.questions.indexOf(q) + 1;
      const grid = groups.models.map(model => `<div class="ex-grid-row"><span class="ex-grid-model">${safe(modelLabel(model))}</span>${groups.presets.map(preset => { const cell = q.cells[model][preset]; return `<span class="ex-cell ${cell}" title="${safe(modelLabel(model))} · ${safe(preset.toUpperCase())} · ${cellLabels[cell]}"></span>`; }).join("")}</div>`).join("");
      return `<tr class="question-row${q.sample_id === current ? " current" : ""}" data-k="${index}" tabindex="0"><td class="num">${index}</td><td><span class="q-meta">${safe(q.sample_id)} · ${safe(q.db_id)} · ${safe(q.difficulty)}</span>${safe(q.question)}</td><td>${grid}</td><td class="num">${number(q.problems)}</td></tr>`;
    }).join("")}</tbody></table>`;
    const box = $("#log-questions"), row = $("tr.current", box);
    if (row) {
      const top = row.offsetTop - box.offsetTop - (box.firstElementChild?.tHead?.offsetHeight || 0);
      if (top < box.scrollTop || row.offsetTop - box.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = Math.max(0, top - 8);
    }
  }
  async function openLogView(id) {
    showView("log");
    window.scrollTo(0, 0);
    await loadLogRuns(id);
    if (id && id !== logState.data?.id) await openLog(id);
  }
  async function initialize() {
    try { state.info = await api("info"); renderInfo(); await loadSamples(); }
    catch (error) {
      $("#global-status").hidden = false;
      $("#global-status").innerHTML = `Không thể kết nối hệ thống thí nghiệm: ${safe(error.message)} <button id="retry-info" class="link-button">Thử lại</button>`;
      $("#dataset-health").textContent = "Không thể kiểm tra dữ liệu";
      $("#model-health").textContent = "Không thể kiểm tra mô hình";
      $("#model-cards").innerHTML = '<p class="muted">Kiểm tra server local rồi thử lại.</p>';
      $("#retry-info").addEventListener("click", initialize);
    }
    loadRuns();
    const linkedRun = location.hash.match(/^#report\/([a-f0-9]{32})$/);
    if (linkedRun) pollJob(linkedRun[1]);
  }
  $$(".nav-tab").forEach(button => button.addEventListener("click", () => {
    if (button.dataset.view === "log") { openLogView(logState.data?.id); return; }
    showView(button.dataset.view);
    if (button.dataset.view === "benchmark") loadRuns();
  }));
  $("#log-run").addEventListener("change", () => openLog($("#log-run").value));
  $("#log-k").addEventListener("input", () => setLogK(Number($("#log-k").value)));
  $("#log-prev").addEventListener("click", () => setLogK(logState.k - 1));
  $("#log-next").addEventListener("click", () => setLogK(logState.k + 1));
  $("#log-metric").addEventListener("change", renderLog);
  $("#log-prompt").addEventListener("click", event => { const card = event.target.closest("[data-explain]"); if (card) openMetricDialog(card.dataset.explain); });
  $("#metric-dialog-close").addEventListener("click", () => $("#metric-dialog").close());
  $("#metric-dialog").addEventListener("click", event => {
    if (event.target === $("#metric-dialog")) { $("#metric-dialog").close(); return; }
    const chip = event.target.closest(".em-chip"); if (chip) setLogK(Number(chip.dataset.k));
    const tab = event.target.closest("#metric-tabs button[data-metric]"); if (tab && logState.dialog) { logState.dialog.metric = tab.dataset.metric; renderMetricDialog(); }
  });
  $("#log-difficulty").addEventListener("change", renderLogQuestions);
  $("#log-problems").addEventListener("change", renderLogQuestions);
  $("#log-chart-presets").addEventListener("click", event => { const button = event.target.closest("button[data-preset]"); if (!button) return; logState.chartPreset = button.dataset.preset; renderLogChart(logMetric(), logSteps(logMetric())); });
  $("#log-questions").addEventListener("click", event => { const row = event.target.closest("tr.question-row"); if (row) setLogK(Number(row.dataset.k)); });
  $("#log-questions").addEventListener("keydown", event => { const row = event.target.closest("tr.question-row"); if (row && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); setLogK(Number(row.dataset.k)); } });
  document.addEventListener("keydown", event => {
    if ($("#view-log").hidden || !logState.data || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.target.closest("input, select, textarea, [contenteditable]")) return;
    if (event.key === "ArrowLeft") { event.preventDefault(); setLogK(logState.k - 1); }
    else if (event.key === "ArrowRight") { event.preventDefault(); setLogK(logState.k + 1); }
  });
  $$("[data-source]").forEach(button => button.addEventListener("click", () => {
    state.source = button.dataset.source;
    $$("[data-source]").forEach(tab => { tab.classList.toggle("active", tab === button); tab.setAttribute("aria-pressed", String(tab === button)); });
    $("#dataset-input").hidden = state.source !== "dataset";
    $("#custom-input").hidden = state.source !== "custom";
    $("#schema-details").hidden = true;
    updateButtons();
  }));
  $("#preset").addEventListener("change", applyPreset);
  ["c1", "c2", "c3", "c4"].forEach(key => $(`#${key}`).addEventListener("change", () => { $("#preset-label").textContent = Object.values(options()).some(Boolean) ? "Tùy chỉnh" : "C0"; }));
  $("#sample-split").addEventListener("change", loadSamples);
  $("#sample-search").addEventListener("input", () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(loadSamples, 300); });
  $("#sample-select").addEventListener("change", renderSample);
  $("#custom-question").addEventListener("input", updateButtons);
  $("#custom-db").addEventListener("input", () => { $("#schema-details").hidden = true; updateButtons(); });
  $("#schema-button").addEventListener("click", loadSchema);
  ["mouseover", "focusin"].forEach(type => $("#schema-content").addEventListener(type, event => { const item = event.target.closest("li.fk"); if (item) highlightReference(item, true); }));
  ["mouseout", "focusout"].forEach(type => $("#schema-content").addEventListener(type, event => { const item = event.target.closest("li.fk"); if (item) highlightReference(item, false); }));
  $("#compare-button").addEventListener("click", compare);
  $("#compare-export").addEventListener("click", () => downloadJson(state.comparison, `visql-compare-${state.comparison?.id || Date.now()}.json`));
  $("#benchmark-split").addEventListener("change", updateButtons);
  $("#final-evaluation").addEventListener("change", updateButtons);
  $("#benchmark-button").addEventListener("click", startBenchmark);
  $("#cancel-button").addEventListener("click", cancelBenchmark);
  $("#refresh-runs").addEventListener("click", loadRuns);
  $("#csv-export").addEventListener("click", () => exportRun("csv"));
  $("#json-export").addEventListener("click", () => exportRun("json"));
  window.addEventListener("hashchange", () => {
    const hash = location.hash;
    const linked = hash.match(/^#report\/([a-f0-9]{32})$/);
    if (hash === "#report" || linked) {
      showView("benchmark"); history.replaceState(null,"",hash);
      loadRuns(); if (linked && state.info) { state.job={id:linked[1]}; pollJob(linked[1]); }
    } else if (hash === "#method") showView("method");
    else if (hash === "#experiment") showView("compare");
    else if (/^#log(?:\/[a-f0-9]{32})?$/.test(hash)) openLogView(hash.slice(5) || logState.data?.id);
  });
  $("#compare-mode").addEventListener("change",updateButtons);
  $("#prompt-preview-button").addEventListener("click",previewPrompts);
  $("#prompt-model").addEventListener("change",fillPromptPresets);
  $("#prompt-preset").addEventListener("change",fillPromptStages);
  $("#prompt-stage").addEventListener("change",renderPromptDiff);
  $("#prompt-preset-steps").addEventListener("click", event => { const button = event.target.closest("button[data-index]"); if (!button) return; $("#prompt-preset").value = button.dataset.index; fillPromptStages(); });
  $("#prompt-stage-tabs").addEventListener("click", event => { const button = event.target.closest("button[data-stage]"); if (!button) return; $("#prompt-stage").value = button.dataset.stage; renderPromptDiff(); });
  $$("[data-diff-mode]").forEach(button => button.addEventListener("click", () => { diffView.mode = button.dataset.diffMode; renderPromptDiff(); }));
  $("#diff-changes-only").addEventListener("change", event => { diffView.changesOnly = event.target.checked; diffView.openFolds.clear(); renderPromptDiff(); });
  $("#prompt-diff").addEventListener("click", event => { const button = event.target.closest(".d-fold"); if (!button) return; diffView.openFolds.add(button.dataset.fold); renderPromptDiff(); });
  $("#report-details-button").addEventListener("click",reportRecords);
  $("#sequence-cancel").addEventListener("click",async()=>{try {if(sequenceId){await api("cancel",{id:sequenceId});notice($("#compare-status"),"Đã yêu cầu dừng sau lượt model hiện tại.");}} catch(error) {notice($("#compare-status"),error.message,true);}});
  if (/^#report(?:\/[a-f0-9]{32})?$/.test(location.hash)) {
    const reportHash = location.hash; showView("benchmark"); history.replaceState(null,"",reportHash);
  }
  else if (location.hash === "#method") showView("method");
  const linkedLog = location.hash.match(/^#log(?:\/([a-f0-9]{32}))?$/);
  if (linkedLog) showView("log");
  initialize().then(() => { if (linkedLog) openLogView(linkedLog[1]); });
})();
