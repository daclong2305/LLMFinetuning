"use strict";
// Pure helpers for browsing a saved benchmark run question by question.
(() => {
  const metricValue = value => value === true ? 1 : value === false ? 0 : value;

  function exCell(record) {
    if (!record) return "pending";
    if (record.status === "error") return "error";
    const ex = record.metrics?.ex;
    if (ex == null) return "na";
    return Number(metricValue(ex)) >= 1 ? "pass" : "fail";
  }

  function orderedIds(declared, seen) {
    const ids = (declared || []).map(item => typeof item === "string" ? item : item?.id).filter(Boolean);
    for (const id of seen) if (!ids.includes(id)) ids.push(id);
    return ids;
  }

  function groupRecords(run) {
    const records = run?.records || [];
    const models = orderedIds(run?.models, records.map(r => r.model_id));
    const presets = orderedIds(run?.presets, records.map(r => r.preset_id));
    const bySample = new Map();
    for (const record of records) {
      if (!bySample.has(record.sample_id)) bySample.set(record.sample_id, []);
      bySample.get(record.sample_id).push(record);
    }
    const sampleOrder = orderedIds(run?.sample_ids, records.map(r => r.sample_id)).filter(id => bySample.has(id));
    const rank = (list, id) => list.indexOf(id);
    const questions = sampleOrder.map(sampleId => {
      const items = bySample.get(sampleId).slice().sort((a, b) => rank(models, a.model_id) - rank(models, b.model_id) || rank(presets, a.preset_id) - rank(presets, b.preset_id));
      const first = items[0];
      const cells = {};
      let problems = 0;
      for (const model of models) {
        cells[model] = {};
        for (const preset of presets) {
          const cell = exCell(items.find(r => r.model_id === model && r.preset_id === preset));
          cells[model][preset] = cell;
          if (cell === "fail" || cell === "error") problems += 1;
        }
      }
      return { sample_id: sampleId, db_id: first.db_id, difficulty: first.difficulty, question: first.question, records: items, cells, problems };
    });
    return { models, presets, questions };
  }

  // Running aggregate after each question, same rule as summarize_records:
  // mean over non-null values; n counts every record seen so far.
  function cumulative(groups, metric) {
    const totals = {};
    for (const model of groups.models) {
      totals[model] = {};
      for (const preset of groups.presets) totals[model][preset] = { sum: 0, eligible: 0, n: 0 };
    }
    return groups.questions.map(question => {
      for (const record of question.records) {
        const total = totals[record.model_id]?.[record.preset_id];
        if (!total) continue;
        total.n += 1;
        const value = metricValue(record.metrics?.[metric]);
        if (value != null) { total.sum += Number(value); total.eligible += 1; }
      }
      const step = {};
      for (const model of groups.models) {
        step[model] = {};
        for (const preset of groups.presets) {
          const t = totals[model][preset];
          step[model][preset] = { value: t.eligible ? t.sum / t.eligible : null, eligible: t.eligible, n: t.n };
        }
      }
      return step;
    });
  }

  function filterQuestions(questions, { difficulty = "", onlyProblems = false } = {}) {
    return questions.filter(q => (!difficulty || q.difficulty === difficulty) && (!onlyProblems || q.problems > 0));
  }

  // Why a record got its EM, from the Spider component scores stored in the log.
  function explainEm(record) {
    if (!record) return { status: "pending", components: [], failed: [] };
    const metrics = record.metrics || {};
    const components = Object.entries(metrics.cm_components || {}).map(([key, value]) => ({
      key, label: value.label_total, pred: value.pred_total, match: value.f1 === 1,
      active: Boolean(value.label_total || value.pred_total),
    }));
    const failed = components.filter(c => !c.match).map(c => c.key);
    if (metrics.em == null) return { status: "na", reason: metrics.unavailable_reasons?.em || "", components, failed };
    if (!components.length) return { status: "invalid", components, failed };
    const em = Number(metricValue(metrics.em));
    return { status: em >= 1 ? "match" : "mismatch", components, failed, tableMismatch: em < 1 && !failed.length };
  }

  // Numerator/denominator behind the cumulative score after k questions.
  function metricBreakdown(groups, metric, model, preset, k) {
    const out = { sum: 0, eligible: 0, n: 0, ones: 0, zeros: 0, na: 0, naReasons: {}, perQuestion: [], value: null };
    groups.questions.slice(0, k).forEach((question, index) => {
      const record = question.records.find(r => r.model_id === model && r.preset_id === preset);
      if (!record) { out.perQuestion.push({ k: index + 1, sample_id: question.sample_id, value: undefined }); return; }
      out.n += 1;
      const raw = metricValue(record.metrics?.[metric]);
      if (raw == null) {
        out.na += 1;
        const reason = record.metrics?.unavailable_reasons?.[metric] || (record.status === "error" ? "Lỗi pipeline" : "Không có lý do được lưu");
        out.naReasons[reason] = (out.naReasons[reason] || 0) + 1;
        out.perQuestion.push({ k: index + 1, sample_id: question.sample_id, value: null });
        return;
      }
      const value = Number(raw);
      out.sum += value; out.eligible += 1;
      if (value >= 1) out.ones += 1; else if (value <= 0) out.zeros += 1;
      out.perQuestion.push({ k: index + 1, sample_id: question.sample_id, value });
    });
    out.value = out.eligible ? out.sum / out.eligible : null;
    return out;
  }

  const api = { exCell, groupRecords, cumulative, filterQuestions, explainEm, metricBreakdown };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else window.RunLog = api;
})();
