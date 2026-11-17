"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const RunLog = require("../../demo/static/run-log.js");

const rec = (sample, model, preset, metrics, status = "ok", extra = {}) => ({
  sample_id: sample, model_id: model, preset_id: preset, status, db_id: "db" + sample.slice(-1),
  difficulty: sample === "dev:1" ? "hard" : "easy", question: "Q " + sample, metrics, ...extra,
});
const fixture = () => ({
  sample_ids: ["dev:1", "dev:2", "dev:3"],
  models: [{ id: "a" }, { id: "b" }],
  presets: [{ id: "p0" }, { id: "p1" }],
  records: [
    rec("dev:1", "a", "p0", { ex: 1, em: 1 }),
    rec("dev:1", "a", "p1", { ex: 0, em: null }),
    rec("dev:1", "b", "p0", { ex: null }, "error"),
    rec("dev:1", "b", "p1", { ex: null }),
    rec("dev:2", "a", "p0", { ex: 1, em: 0 }),
    rec("dev:2", "z", "p0", { ex: 1 }),
  ],
});

test("exCell classifies records", () => {
  assert.equal(RunLog.exCell(undefined), "pending");
  assert.equal(RunLog.exCell({ status: "error", metrics: { ex: null } }), "error");
  assert.equal(RunLog.exCell({ status: "ok", metrics: { ex: null } }), "na");
  assert.equal(RunLog.exCell({ status: "ok", metrics: { ex: 1 } }), "pass");
  assert.equal(RunLog.exCell({ status: "ok", metrics: { ex: 0 } }), "fail");
  assert.equal(RunLog.exCell({ status: "ok", metrics: { ex: true } }), "pass");
});

test("groupRecords orders questions, models, presets and builds cells", () => {
  const g = RunLog.groupRecords(fixture());
  assert.deepEqual(g.questions.map(q => q.sample_id), ["dev:1", "dev:2"]);
  assert.deepEqual(g.models, ["a", "b", "z"]);
  assert.deepEqual(g.presets, ["p0", "p1"]);
  const q1 = g.questions[0];
  assert.deepEqual(q1.cells, { a: { p0: "pass", p1: "fail" }, b: { p0: "error", p1: "na" }, z: { p0: "pending", p1: "pending" } });
  assert.equal(q1.problems, 2);
  assert.equal(q1.db_id, "db1");
  assert.equal(q1.difficulty, "hard");
  assert.deepEqual(q1.records.map(r => r.model_id + r.preset_id), ["ap0", "ap1", "bp0", "bp1"]);
  assert.equal(g.questions[1].cells.b.p1, "pending");
  assert.equal(g.questions[1].cells.z.p0, "pass");
});

test("cumulative averages non-null values in run order", () => {
  const g = RunLog.groupRecords(fixture());
  const steps = RunLog.cumulative(g, "em");
  assert.equal(steps.length, 2);
  assert.deepEqual(steps[0].a.p0, { value: 1, eligible: 1, n: 1 });
  assert.deepEqual(steps[0].a.p1, { value: null, eligible: 0, n: 1 });
  assert.deepEqual(steps[1].a.p0, { value: 0.5, eligible: 2, n: 2 });
  assert.deepEqual(steps[1].a.p1, { value: null, eligible: 0, n: 1 });
  assert.deepEqual(steps[1].b.p1, { value: null, eligible: 0, n: 1 });
  assert.deepEqual(steps[0].z.p0, { value: null, eligible: 0, n: 0 });
});

test("filterQuestions by difficulty and problems", () => {
  const qs = RunLog.groupRecords(fixture()).questions;
  assert.deepEqual(RunLog.filterQuestions(qs, { onlyProblems: true }).map(q => q.sample_id), ["dev:1"]);
  assert.deepEqual(RunLog.filterQuestions(qs, { difficulty: "easy" }).map(q => q.sample_id), ["dev:2"]);
  assert.equal(RunLog.filterQuestions(qs, {}).length, 2);
});

const realLog = path.join(__dirname, "../../reports/experiments/3691cd10d73f4b43879a068701ffdd4e.json");
test("final cumulative step matches stored summary", { skip: !fs.existsSync(realLog) && "sample log not present" }, () => {
  const run = JSON.parse(fs.readFileSync(realLog, "utf8"));
  const g = RunLog.groupRecords(run);
  assert.equal(g.questions.length, 50);
  for (const metric of ["em", "cm", "ex", "ts", "ves"]) {
    const last = RunLog.cumulative(g, metric).at(-1);
    for (const row of run.summary.rows) {
      const cell = last[row.model_id][row.preset_id];
      assert.equal(cell.n, row.n, `${metric} ${row.model_id} ${row.preset_id} n`);
      assert.equal(cell.eligible, row.eligible_n[metric]);
      if (row[metric] == null) assert.equal(cell.value, null);
      else assert.ok(Math.abs(cell.value - row[metric]) < 1e-9, `${metric} ${row.model_id} ${row.preset_id}`);
    }
  }
});

const comp = (label, pred, f1) => ({ acc: f1, rec: f1, f1, label_total: label, pred_total: pred });
test("explainEm reports matching and mismatching components", () => {
  const match = RunLog.explainEm({ status: "ok", metrics: { em: 1, cm_components: { select: comp(2, 2, 1), where: comp(0, 0, 1) } } });
  assert.equal(match.status, "match");
  assert.deepEqual(match.components.map(c => [c.key, c.label, c.pred, c.match, c.active]), [["select", 2, 2, true, true], ["where", 0, 0, true, false]]);
  const miss = RunLog.explainEm({ status: "ok", metrics: { em: 0, cm_components: { select: comp(2, 2, 1), order: comp(1, 0, 0) } } });
  assert.equal(miss.status, "mismatch");
  assert.deepEqual(miss.failed, ["order"]);
  assert.equal(miss.tableMismatch, false);
  const tables = RunLog.explainEm({ status: "ok", metrics: { em: 0, cm_components: { select: comp(1, 1, 1) } } });
  assert.equal(tables.tableMismatch, true);
  assert.equal(RunLog.explainEm({ status: "error", metrics: { em: 0, cm_components: {} } }).status, "invalid");
  const na = RunLog.explainEm({ status: "ok", metrics: { em: null, unavailable_reasons: { em: "Gold SQL unsupported" } } });
  assert.deepEqual([na.status, na.reason], ["na", "Gold SQL unsupported"]);
  assert.equal(RunLog.explainEm(undefined).status, "pending");
});

test("metricBreakdown counts values up to question k", () => {
  const g = RunLog.groupRecords(fixture());
  g.questions[0].records[1].metrics.unavailable_reasons = { em: "lý do" };
  const b1 = RunLog.metricBreakdown(g, "em", "a", "p1", 1);
  assert.deepEqual([b1.sum, b1.eligible, b1.n, b1.na, b1.value], [0, 0, 1, 1, null]);
  assert.deepEqual(b1.naReasons, { "lý do": 1 });
  const b2 = RunLog.metricBreakdown(g, "em", "a", "p0", 2);
  assert.deepEqual([b2.sum, b2.eligible, b2.n, b2.ones, b2.zeros, b2.value], [1, 2, 2, 1, 1, 0.5]);
  assert.deepEqual(b2.perQuestion.map(q => [q.k, q.sample_id, q.value]), [[1, "dev:1", 1], [2, "dev:2", 0]]);
});
