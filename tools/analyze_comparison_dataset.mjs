// PostgreSQL-анализ второй выборки. Исходные строки в отчёт не включаются.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const [dependencies, preparedPath] = process.argv.slice(2);
if (!dependencies || !preparedPath) {
  throw new Error('Использование: node tools/analyze_comparison_dataset.mjs КАТАЛОГ_PGLITE ПОДГОТОВЛЕННЫЙ_JSON');
}
const require = createRequire(import.meta.url);
const { PGlite } = require(path.join(path.resolve(dependencies), 'node_modules/@electric-sql/pglite'));
const caseRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sqlDir = path.join(caseRoot, 'sql/comparison');
const files = ['00_schema.sql', '01_coverage.sql', '02_paired_accuracy.sql', '03_outcomes.sql', '04_reference_audit.sql'];
const sql = Object.fromEntries(files.map(name => [name, fs.readFileSync(path.join(sqlDir, name), 'utf8')]));
const prepared = JSON.parse(fs.readFileSync(preparedPath, 'utf8'));
assert.equal(prepared.source.reference, 'true_score', 'Эталон второго источника должен быть true_score');
assert.equal(prepared.rows.length, prepared.source.rows);

async function insertRows(db, rows) {
  for (const row of rows) {
    await db.query('INSERT INTO benchmark_works VALUES ($1, $2, $3)',
      [row.work_id, row.task_number, row.original_row_id ?? null]);
    for (const [key, field] of [['predel', 'predel_score'], ['their', 'their_score']]) {
      if (row[field] != null) await db.query('INSERT INTO benchmark_scores VALUES ($1, $2, $3)',
        [row.work_id, key, row[field]]);
    }
    for (const [key, field] of [['team', 'true_score'], ['curator', 'curator_score']]) {
      if (row[field] != null) await db.query('INSERT INTO benchmark_references VALUES ($1, $2, $3)',
        [row.work_id, key, row[field]]);
    }
  }
}

async function queries(db) {
  const result = {};
  for (const name of files.slice(1)) result[name] = (await db.query(sql[name])).rows;
  return result;
}

const tests = [];
const testDb = new PGlite();
try {
  await testDb.exec(sql['00_schema.sql']);
  await insertRows(testDb, [
    {work_id: 1, task_number: 13, true_score: 0, curator_score: 1, predel_score: 0, their_score: 1},
    {work_id: 2, task_number: 13, true_score: 2, curator_score: 2, predel_score: 1, their_score: 2},
    {work_id: 3, task_number: 14, true_score: 1, predel_score: null, their_score: 1},
    {work_id: 4, task_number: 14, true_score: null, predel_score: 0, their_score: 0},
  ]);
  const result = await queries(testDb);
  assert.deepEqual(result['01_coverage.sql'].map(r => [r.total_works, r.paired_works]), [[2, 2], [2, 0]]);
  tests.push('LEFT JOIN сохраняет все работы; пропуски исключаются только из общей выборки');
  const totals = result['02_paired_accuracy.sql'].filter(r => r.task_number === null);
  assert.equal(totals.length, 2);
  for (const r of totals) {
    assert.equal(r.works, 2); assert.equal(r.exact_matches, 1); assert.equal(Number(r.accuracy_pct), 50);
  }
  tests.push('Нулевой балл сохраняется; обе системы имеют одинаковый знаменатель');
  assert.equal(result['04_reference_audit.sql'][0].different_scores, 1);
  assert.deepEqual(result['03_outcomes.sql'].map(r => r.works), [1, 1]);
  tests.push('Эталон команды имеет приоритет над отличающейся оценкой куратора');
  for (const [name, statement, code] of [
    ['Повтор пары работа/серия отклоняется', "INSERT INTO benchmark_scores VALUES (1, 'predel', 0)", '23505'],
    ['Оценка несуществующей работы отклоняется', "INSERT INTO benchmark_scores VALUES (999, 'predel', 0)", '23503'],
    ['Повтор эталона отклоняется', "INSERT INTO benchmark_references VALUES (1, 'team', 0)", '23505'],
  ]) {
    await testDb.exec('BEGIN');
    await assert.rejects(testDb.exec(statement), error => error.code === code);
    await testDb.exec('ROLLBACK'); tests.push(name);
  }
  await testDb.exec('TRUNCATE benchmark_scores, benchmark_references, benchmark_works');
  const empty = await queries(testDb);
  assert.equal(empty['02_paired_accuracy.sql'].length, 0);
  assert.equal(empty['03_outcomes.sql'].length, 0);
  assert.equal(empty['04_reference_audit.sql'][0].compared_references, 0);
  tests.push('Пустая выборка не превращается в нулевую точность');
} finally { await testDb.close(); }

const db = new PGlite();
try {
  await db.exec(sql['00_schema.sql']);
  await insertRows(db, prepared.rows);
  const results = await queries(db);
  const paired = prepared.rows.filter(r => r.true_score != null && r.predel_score != null && r.their_score != null);
  // Независимый пересчёт знаменателя, совпадений и MAE каждой группы SQL.
  for (const actual of results['02_paired_accuracy.sql']) {
    const group = paired.filter(r => actual.task_number === null || r.task_number === actual.task_number);
    const field = actual.model_name === 'PredelAI' ? 'predel_score' : 'their_score';
    const exact = group.filter(r => Number(r[field]) === Number(r.true_score)).length;
    const mae = group.reduce((sum, r) => sum + Math.abs(Number(r[field]) - Number(r.true_score)), 0) / group.length;
    assert.equal(actual.works, group.length);
    assert.equal(actual.exact_matches, exact);
    assert.ok(Math.abs(Number(actual.accuracy_pct) - 100 * exact / group.length) <= 0.005001);
    assert.ok(Math.abs(Number(actual.mae) - mae) <= 0.0005001);
  }
  assert.equal(results['01_coverage.sql'].reduce((n, r) => n + r.total_works, 0), prepared.rows.length);
  assert.equal(results['01_coverage.sql'].reduce((n, r) => n + r.paired_works, 0), paired.length);
  assert.equal(results['03_outcomes.sql'].reduce((n, r) => n + r.works, 0), paired.length);
  const comparableRefs = prepared.rows.filter(r => r.true_score != null && r.curator_score != null);
  const audit = results['04_reference_audit.sql'][0];
  assert.equal(audit.compared_references, comparableRefs.length);
  assert.equal(audit.different_scores, comparableRefs.filter(r => Number(r.true_score) !== Number(r.curator_score)).length);
  const individual = ['predel_score', 'their_score'].map(field => {
    const rows = prepared.rows.filter(r => r.true_score != null && r[field] != null);
    return {field, works: rows.length,
      exact_matches: rows.filter(r => Number(r[field]) === Number(r.true_score)).length,
      absolute_error_sum: rows.reduce((n, r) => n + Math.abs(Number(r[field]) - Number(r.true_score)), 0)};
  });
  const report = {
    calculated_at: new Date().toISOString(), source: prepared.source,
    engine: (await db.query('SELECT version()')).rows[0].version,
    pglite_version: require(path.join(path.resolve(dependencies), 'node_modules/@electric-sql/pglite/package.json')).version,
    queries_executed: 4, paired_works: paired.length,
    reference_confirmed_by_owner: true, independent_holdout_confirmed: false,
    source_rows_included_in_case: false, application_database_used: false,
    verification: {passed: tests.length, scenarios: tests, independent_recalculation_passed: true},
    results, individual_cohorts_not_for_direct_comparison: individual,
    sha256: Object.fromEntries(files.map(name => [name, crypto.createHash('sha256').update(sql[name]).digest('hex')])),
    tool_sha256: Object.fromEntries(['prepare_comparison_dataset.py', 'analyze_comparison_dataset.mjs'].map(name =>
      [name, crypto.createHash('sha256').update(fs.readFileSync(path.join(caseRoot, 'tools', name))).digest('hex')]))
  };
  const destination = path.join(caseRoot, 'verification/comparison-analysis-report.json');
  fs.writeFileSync(destination, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({rows: prepared.rows.length, paired: paired.length, tests: tests.length, report: destination}));
} finally { await db.close(); }
