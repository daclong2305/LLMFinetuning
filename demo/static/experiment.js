"use strict";
(() => {
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const state = { info: null, samples: [], source: "dataset", comparison: null, job: null, poll: null, searchTimer: null, sampleRequest: 0, busy: false, starting: false };
  const scoreKeys = ["em", "cm", "ex", "ts", "ves"];
  const safe = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const numeric = value => typeof value === "number" && Number.isFinite(value);
  const number = (value, decimals = 0) => numeric(value) ? value.toLocaleString("vi-VN", { maximumFractionDigits: decimals }) : "N/A";
  const percentage = value => numeric(value) || typeof value === "boolean" ? `${number(Number(value) * 100, 1)}%` : "N/A";
  const score = (key, value) => key === "ves" ? number(value, 3) : percentage(value);
  const duration = value => numeric(value) ? value >= 1000 ? `${number(value / 1000, 2)} s` : `${number(value)} ms` : "N/A";
  const money = value => numeric(value) ? `$${value.toLocaleString("en-US", { minimumFractionDigits: value > 0 ? 4 : 2, maximumFractionDigits: 6 })}` : "N/A";
  const pretty = value => typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const selected = selector => $$(selector).filter(input => input.checked && !input.disabled).map(input => input.value);
  const modelLabel = id => state.info?.models?.find(model => model.id === id)?.label || id || "Mô hình";
  const statusLabels = { ready: "Sẵn sàng", completed: "Hoàn tất", complete: "Hoàn tất", success: "Thành công", ok: "Thành công", error: "Lỗi", failed: "Thất bại", unavailable: "Chưa sẵn sàng", pending: "Đang chờ", queued: "Đang chờ", running: "Đang chạy", cancelled: "Đã hủy", cancel_requested: "Đang hủy", partial: "Chưa hoàn tất" };
  const statusBadge = status => `<span class="badge ${["failed", "error"].includes(status) ? "error" : ["unavailable", "cancelled", "partial"].includes(status) ? "warn" : ["running", "pending", "queued"].includes(status) ? "neutral" : ""}">${safe(statusLabels[status] || status || "Chưa đo")}</span>`;
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
    $("#model-health").textContent = `${available.length} / ${models.length} mô hình có thể suy luận`;
    $("#model-cards").innerHTML = models.length ? models.map(model => {
      const ready = model.available === true;
      const trained = ready && model.trained === true;
      return `<label class="model-card ${ready ? "selected" : "unavailable"}"><input class="compare-model" type="checkbox" value="${safe(model.id)}" ${ready ? "checked" : "disabled"} aria-label="Chọn ${safe(model.label || model.id)}"><span class="model-body"><b>${safe(model.label || model.id)}</b><span class="model-name">${safe(model.model || model.id)}</span><span class="model-row"><span class="provider">${safe(model.provider || "Adapter")} ${trained ? "· checkpoint xác minh" : ""}</span><span class="badge ${ready ? "" : "warn"}">${ready ? "Sẵn sàng" : "Chưa sẵn sàng"}</span></span>${!ready ? `<span class="model-reason">${safe(model.reason || "Chưa đáp ứng điều kiện suy luận.")}</span>` : ""}</span></label>`;
    }).join("") : '<p class="muted">Chưa đăng ký mô hình. Thêm cấu hình để bắt đầu.</p>';
    $("#benchmark-models").innerHTML = models.map(model => `<label class="check-option"><input class="benchmark-model" type="checkbox" value="${safe(model.id)}" ${model.available === true ? "checked" : "disabled"}><span>${safe(model.label || model.id)}<small>${safe(model.available === true ? model.model || model.provider : model.reason || "Chưa sẵn sàng")}</small></span></label>`).join("");
    const list = presets();
    $("#preset").innerHTML = list.map(preset => `<option value="${safe(preset.id)}">${safe(preset.label || preset.name || preset.id)}</option>`).join("") || '<option value="c0">C0 · Baseline</option>';
    $("#benchmark-presets").innerHTML = list.map((preset, index) => `<label class="check-option"><input class="benchmark-preset" type="checkbox" value="${safe(preset.id)}" ${index === 0 ? "checked" : ""}><span>${safe(preset.label || preset.name || preset.id)}${preset.description ? `<small>${safe(preset.description)}</small>` : ""}</span></label>`).join("");
    $("#model-setup").innerHTML = '<p>Qwen base: chạy Ollama và tải đúng model đã đăng ký. GPT: thiết lập <code>OPENAI_API_KEY</code> trong môi trường local. Qwen fine-tuned: huấn luyện và đăng ký checkpoint riêng đã có manifest.</p>';
    $("#training-info").innerHTML = `<pre>${safe(pretty(info.training || { state: "Chưa có thông tin checkpoint." }))}</pre>`;
    $("#dataset-details").innerHTML = `<details><summary>Phiên bản, kiểm tra split & khả năng thực thi</summary><pre>${safe(pretty(dataset))}</pre></details>`;
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
    $("#preset-label").textContent = preset?.id?.toUpperCase() || "C0";
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
      $("#sample-count").textContent = `· ${number(data.total)} mẫu${data.total > state.samples.length ? ` · hiển thị ${state.samples.length} đầu tiên` : ""}`;
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
    $("#sample-preview").innerHTML = sample ? `<p>${safe(sample.question)}</p><div class="sample-meta"><span>▤ ${safe(sample.db_id)}</span><span class="badge neutral">${safe(sample.difficulty || "Chưa phân loại")}</span><span>${safe(sample.id)}</span></div>` : '<p class="muted">Không có mẫu để chọn. Kiểm tra dữ liệu hoặc thay đổi từ khóa tìm kiếm.</p>';
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
      $("#schema-content").innerHTML = Object.keys(schema).length ? Object.entries(schema).map(([name, table]) => `<div class="schema-table"><h3>${safe(name)}</h3>${table.description ? `<p class="tiny-note">${safe(table.description)}</p>` : ""}<pre>${safe(table.ddl || pretty(table))}</pre></div>`).join("") : '<p class="muted">Database này chưa có schema.</p>';
      $("#schema-details").hidden = false;
      $("#schema-details").open = true;
    } catch (error) { notice($("#compare-status"), `Không thể tải schema: ${error.message}`, true); }
    finally { button.textContent = "▤ Xem schema"; updateButtons(); }
  }
  const metricReason = (metrics, key) => {
    const reasons = metrics.unavailable_reasons || metrics.reasons || {};
    return typeof reasons === "string" ? reasons : reasons[key] || reasons.evaluation || "Chưa có phép đo hoặc tài sản đánh giá phù hợp.";
  };
  function executionView(execution) {
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
  function renderComparison(data) {
    state.comparison = data;
    const results = data.results || [];
    const container = $("#compare-results");
    container.className = results.length ? "results-grid" : "empty-state";
    container.innerHTML = results.length ? results.map(result => {
      const metrics = result.metrics || {};
      const missing = scoreKeys.filter(key => metrics[key] == null);
      const success = metrics.execution_success;
      return `<article class="result-card"><header class="result-head"><h3>${safe(result.label || modelLabel(result.model_id))}</h3>${statusBadge(result.status)}</header><div class="result-body"><div class="result-label">SQL ĐƯỢC SINH</div><div class="sql-block"><pre>${safe(result.sql || "Chưa sinh được SQL.")}</pre></div>${result.error ? `<div class="result-error">${safe(typeof result.error === "object" ? pretty(result.error) : result.error)}</div>` : ""}<div class="metrics-grid">${scoreKeys.map(key => `<div class="metric" title="${safe(metrics[key] == null ? metricReason(metrics, key) : key === "em" ? "Khớp cấu trúc SQL" : key === "cm" ? "F1 thành phần SQL" : "Chỉ số đánh giá")}"><span>${key.toUpperCase()}</span><strong class="${metrics[key] == null ? "na" : ""}">${score(key, metrics[key])}</strong><small>${metrics[key] == null ? "chưa đo được" : "đã đánh giá"}</small></div>`).join("")}</div><div class="usage-grid"><div>Độ trễ toàn pipeline<b>${duration(metrics.latency_ms)}</b></div><div>Độ trễ SQL<b>${duration(metrics.sql_latency_ms)}</b></div><div>Input / Output tokens<b>${number(metrics.input_tokens)} / ${number(metrics.output_tokens)}</b></div><div>Lượt gọi / Input cached<b>${number(metrics.calls)} / ${number(metrics.cached_input_tokens)}</b></div><div>Chi phí API<b>${money(metrics.cost_usd)}${metrics.cost_usd === 0 ? " · local" : ""}</b></div><div>Thực thi / Cú pháp<b>${success == null ? "N/A" : success ? "Thành công" : "Lỗi"} / ${metrics.syntax_valid == null ? "N/A" : metrics.syntax_valid ? "Hợp lệ" : "Lỗi"}</b></div></div></div><details><summary>Kết quả thực thi</summary>${executionView(result.execution)}</details>${missing.length ? `<details><summary>Vì sao chỉ số là N/A? · ${missing.length} chỉ số</summary>${missing.map(key => `<p><b>${key.toUpperCase()}</b> · ${safe(metricReason(metrics, key))}</p>`).join("")}</details>` : ""}<details><summary>Trace suy luận · ${(result.trace || []).length} bước</summary>${traceView(result.trace || [])}</details></article>`;
    }).join("") : '<h3>Không có kết quả trả về</h3><p>Kiểm tra trạng thái mô hình và thử lại.</p>';
    $$(".result-card", container).forEach((card, index) => {
      const result = results[index];
      const metrics = result.metrics || {};
      const provider = state.info?.models?.find(model => model.id === result.model_id)?.provider;
      const costCell = $$(".usage-grid b", card)[4];
      if (costCell) costCell.textContent = `${money(metrics.cost_usd)}${metrics.cost_usd === 0 && provider === "ollama" ? " · API local" : ""}`;
      const details = document.createElement("details");
      details.innerHTML = `<summary>Thành phần CM & độ phủ usage</summary><p>Chi phí API không bao gồm phần cứng và huấn luyện. N/A usage nghĩa là adapter chưa trả đủ thông tin; số đã biết vẫn được lưu.</p><pre>${safe(pretty({ cm_components: metrics.cm_components || null, calls: metrics.calls, repair_calls: metrics.repair_calls, input_tokens_coverage: metrics.input_tokens_coverage, output_tokens_coverage: metrics.output_tokens_coverage, cached_input_tokens_coverage: metrics.cached_input_tokens_coverage, cost_usd_coverage: metrics.cost_usd_coverage, known_input_tokens: metrics.known_input_tokens, known_output_tokens: metrics.known_output_tokens, known_cost_usd: metrics.known_cost_usd, options: result.options }))}</pre>`;
      card.append(details);
    });
    $("#compare-export").disabled = !results.length;
    const gold = data.sample?.gold_sql;
    $("#gold-details").hidden = !gold;
    $("#gold-details").open = false;
    $("#gold-sql").textContent = gold || "";
  }
  async function compare() {
    if ($("#compare-button").disabled) return;
    state.busy = true;
    updateButtons();
    $("#compare-button").textContent = "Đang suy luận…";
    $("#compare-button").classList.add("loading-pulse");
    notice($("#compare-status"), "Các mô hình đang xử lý cùng câu hỏi. Thời gian chạy phụ thuộc mô hình và C1–C4.");
    const body = { model_ids: selected(".compare-model"), options: options() };
    if (state.source === "dataset") body.sample_id = currentSample().id;
    else { body.question = $("#custom-question").value.trim(); body.db_id = dbId(); }
    try {
      const data = await api("compare", body);
      renderComparison(data);
      const errors = (data.results || []).filter(result => !["ok", "success", "completed", "complete"].includes(result.status)).length;
      notice($("#compare-status"), `Đã nhận ${data.results?.length || 0} kết quả${errors ? ` · ${errors} mô hình có lỗi hoặc chưa hoàn tất` : ""}. Run ${data.id || ""}`);
    } catch (error) { notice($("#compare-status"), `Không thể so sánh: ${error.message}`, true); }
    finally { state.busy = false; $("#compare-button").innerHTML = 'Chạy so sánh <span aria-hidden="true">→</span>'; $("#compare-button").classList.remove("loading-pulse"); updateButtons(); }
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
    const rows = summary?.rows || [];
    if (!rows.length) {
      $("#benchmark-chart").className = "chart-empty";
      $("#benchmark-chart").textContent = "Chưa có số liệu benchmark để hiển thị.";
      $("#benchmark-table").innerHTML = '<p class="muted">Chưa có kết quả. Tiến độ và kết quả một phần sẽ cập nhật tự động.</p>';
      $("#difficulty-results").innerHTML = "";
      return;
    }
    $("#benchmark-chart").className = "bar-chart";
    $("#benchmark-chart").innerHTML = rows.map(row => `<div class="bar-chart-row"><div class="bar-chart-name"><b>${safe(modelLabel(row.model_id))}</b><br><span class="muted">${safe(row.preset_id)}</span></div><div class="bars">${["em", "cm", "ex"].map(key => `<div class="bar-line"><span class="bar-key">${key.toUpperCase()}</span><div class="bar-track"><div class="bar-fill ${key}" data-width="${numeric(row[key]) ? Math.max(0, Math.min(100, row[key] * 100)) : 0}"></div></div><span class="bar-value">${percentage(row[key])}</span></div>`).join("")}</div></div>`).join("");
    $$("#benchmark-chart .bar-fill").forEach(bar => { bar.style.width = `${bar.dataset.width}%`; });
    const columns = ["Mô hình / cấu hình", "Mẫu", "EM", "CM", "EX", "TS", "VES", "Thực thi", "Cú pháp", "Latency p50 / p95", "SQL TB", "Input / Output", "Lượt gọi", "API cost"];
    $("#benchmark-table").innerHTML = `<table><thead><tr>${columns.map(column => `<th>${column}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr><td>${safe(modelLabel(row.model_id))}<small>${safe(row.preset_id)}</small></td><td>${number(row.n)} / ${number(row.expected_n)}<small>đã đo / dự kiến</small></td>${scoreKeys.map(key => `<td>${score(key, row[key])}<small>coverage ${safe(coverage(row, key))}</small></td>`).join("")}<td>${percentage(row.execution_success_rate)}</td><td>${percentage(row.syntax_valid_rate)}</td><td>${duration(row.p50_latency_ms)} / ${duration(row.p95_latency_ms)}</td><td>${duration(row.mean_sql_latency_ms)}</td><td>${number(row.input_tokens)} / ${number(row.output_tokens)}</td><td>${number(row.calls)}</td><td>${money(row.cost_usd)}${row.cost_usd === 0 ? '<small>API local · chưa gồm phần cứng</small>' : ""}</td></tr>`).join("")}</tbody></table>`;
    const table = $("table", $("#benchmark-table"));
    const cachedHead = document.createElement("th");
    cachedHead.textContent = "Input cached";
    $("thead tr", table).append(cachedHead);
    $$("tbody tr", table).forEach((tr, index) => {
      const row = rows[index];
      const cachedCell = document.createElement("td");
      cachedCell.innerHTML = `${number(row.cached_input_tokens)}<small>coverage ${safe(coverage(row, "cached_input_tokens"))}</small>`;
      tr.append(cachedCell);
      scoreKeys.forEach((key, offset) => {
        const cell = tr.children[offset + 2];
        const interval = row.intervals?.[key];
        cell.title = row[key] == null ? (row.unavailable_reasons?.[key] || []).join("; ") || "Chưa có phép đo hợp lệ." : interval ? `Wilson 95%: ${percentage(interval[0])} – ${percentage(interval[1])}` : "Điểm tính trên các mẫu có phép đo hợp lệ; xem coverage.";
      });
    });
    $("#difficulty-results").innerHTML = `<details class="difficulty-block"><summary>Độ phủ, lý do N/A & khoảng tin cậy</summary><pre>${safe(pretty(rows.map(row => ({ model_id: row.model_id, preset_id: row.preset_id, errors: row.errors, complete: row.complete, coverage: row.coverage, eligible_n: row.eligible_n, intervals: row.intervals, unavailable_reasons: row.unavailable_reasons, cm_components: row.cm_components }))))}</pre></details>` + rows.filter(row => row.per_difficulty && Object.keys(row.per_difficulty).length).map(row => `<details class="difficulty-block"><summary>Theo độ khó · ${safe(modelLabel(row.model_id))} / ${safe(row.preset_id)}</summary><pre>${safe(pretty(row.per_difficulty))}</pre></details>`).join("") + (summary.notes?.length ? `<p class="tiny-note">${safe(summary.notes.join(" "))}</p>` : "");
  }
  function renderJob(job) {
    state.job = job;
    const done = job.done || 0;
    const total = job.total || 0;
    const terminal = !["running", "pending", "queued", "cancel_requested"].includes(job.state);
    $("#job-state").outerHTML = statusBadge(job.state).replace('<span class="', '<span id="job-state" class="');
    $("#job-progress").textContent = `${number(done)} / ${number(total)} lượt thí nghiệm${job.state === "cancelled" ? " · kết quả một phần" : ""}`;
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
      const job = await api("benchmark", { split: $("#benchmark-split").value, limit, model_ids: selected(".benchmark-model"), preset_ids: selected(".benchmark-preset"), final_evaluation: $("#benchmark-split").value === "test" && $("#final-evaluation").checked });
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
      $("#run-history").innerHTML = data.runs?.length ? data.runs.map(run => `<div class="history-row"><div><strong>${safe(run.id)}</strong><small>${safe(run.split || "dev")} · ${safe(run.created_at ? new Date(run.created_at).toLocaleString("vi-VN") : "Không có thời gian")} · ${run.summary?.rows?.length || 0} nhóm kết quả</small></div><div class="history-actions">${statusBadge(run.state)}<button class="button subtle small load-run" data-run="${safe(run.id)}">Xem →</button></div></div>`).join("") : '<p class="muted">Chưa có run được lưu. Benchmark đầu tiên sẽ xuất hiện tại đây.</p>';
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
  async function initialize() {
    try { state.info = await api("info"); renderInfo(); await loadSamples(); }
    catch (error) {
      $("#global-status").hidden = false;
      $("#global-status").innerHTML = `Không thể kết nối hệ thống thí nghiệm: ${safe(error.message)} <button id="retry-info" class="button subtle small">Thử lại ↻</button>`;
      $("#dataset-health").textContent = "Không thể kiểm tra dữ liệu";
      $("#model-health").textContent = "Không thể kiểm tra mô hình";
      $("#model-cards").innerHTML = '<p class="muted">Kiểm tra server local rồi thử lại.</p>';
      $("#retry-info").addEventListener("click", initialize);
    }
    loadRuns();
  }
  $$(".nav-tab").forEach(button => button.addEventListener("click", () => {
    $$(".nav-tab").forEach(tab => { const active = tab === button; tab.classList.toggle("active", active); tab.setAttribute("aria-pressed", String(active)); });
    $$(".view").forEach(view => { view.hidden = view.id !== `view-${button.dataset.view}`; });
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
  ["c1", "c2", "c3", "c4"].forEach(key => $(`#${key}`).addEventListener("change", () => { $("#preset-label").textContent = Object.values(options()).some(Boolean) ? "TÙY CHỈNH" : "C0"; }));
  $("#sample-split").addEventListener("change", loadSamples);
  $("#sample-search").addEventListener("input", () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(loadSamples, 300); });
  $("#sample-select").addEventListener("change", renderSample);
  $("#custom-question").addEventListener("input", updateButtons);
  $("#custom-db").addEventListener("input", () => { $("#schema-details").hidden = true; updateButtons(); });
  $("#schema-button").addEventListener("click", loadSchema);
  $("#compare-button").addEventListener("click", compare);
  $("#compare-export").addEventListener("click", () => downloadJson(state.comparison, `visql-compare-${state.comparison?.id || Date.now()}.json`));
  $("#benchmark-split").addEventListener("change", updateButtons);
  $("#final-evaluation").addEventListener("change", updateButtons);
  $("#benchmark-button").addEventListener("click", startBenchmark);
  $("#cancel-button").addEventListener("click", cancelBenchmark);
  $("#refresh-runs").addEventListener("click", loadRuns);
  $("#csv-export").addEventListener("click", () => exportRun("csv"));
  $("#json-export").addEventListener("click", () => exportRun("json"));
  initialize();
})();
