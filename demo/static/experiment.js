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
      $("#run-history").innerHTML = data.runs?.length ? data.runs.map(run => `<div class="history-row"><div><strong>${safe(run.id)}</strong><small>${run.scope === "full" ? "FULL" : "PILOT"} · ${run.purpose === "prompt_comparison" ? "Prompt" : "Benchmark"} · ${safe(run.split || "dev")} · ${safe(run.created_at ? new Date(run.created_at).toLocaleString("vi-VN") : "Không có thời gian")} · ${run.done || 0}/${run.total || 0} kết quả</small></div><div class="history-actions">${statusBadge(run.state)}<button class="button subtle small load-run" data-run="${safe(run.id)}">Xem</button></div></div>`).join("") : '<p class="muted">Chưa có lượt chạy nào được lưu.</p>';
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
    history.replaceState(null, "", name === "benchmark" ? "#report" : name === "method" ? "#method" : "#experiment");
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
    showView(button.dataset.view);
    if (button.dataset.view === "benchmark") loadRuns();
  }));
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
  initialize();
})();
