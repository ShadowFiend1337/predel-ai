// Выполнить семь SQL-запросов на подготовленном реальном снимке.
// node tools/analyze_sql_dataset.mjs /tmp/predel-sql-validation /tmp/predel-real-sql
// В кейс записываются только агрегаты; подробные результаты остаются в рабочем каталоге.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const [dependencyPath, workingPath] = process.argv.slice(2);
if (!dependencyPath || !workingPath) throw new Error('Укажите каталоги PGlite и подготовленного снимка');
const working = path.resolve(workingPath);
const relative = path.relative(path.dirname(root), working);
if (!relative.startsWith('..' + path.sep) && !path.isAbsolute(relative)) throw new Error('Рабочий каталог должен находиться вне проекта');
const require = createRequire(path.join(path.resolve(dependencyPath), 'package.json'));
const { PGlite } = require('@electric-sql/pglite');
const packageInfo = JSON.parse(await readFile(path.join(dependencyPath, 'node_modules/@electric-sql/pglite/package.json'), 'utf8'));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const manifest = JSON.parse(await readFile(path.join(working, 'manifest.json'), 'utf8'));
const preparedBytes = await readFile(path.join(working, 'prepared.json'));
assert.equal(digest(preparedBytes), manifest.prepared_sha256);
const rows = JSON.parse(preparedBytes);
assert.equal(rows.length, manifest.prepared_rows);
for (const field of ['answer_id', 'ai_check_id']) assert.equal(new Set(rows.map(r => r[field])).size, rows.length, `Неоднозначная гранулярность: ${field}`);
const fields = ['source_row', 'answer_id', 'ai_check_id', 'task_id', 'question_id', 'task_number', 'stud_id', 'max_points', 'ai_points', 'curator_points', 'ai_comment', 'curator_comment', 'sent_to_review_at', 'curator_reviewed_at', 'sent_to_review_at_raw', 'curator_reviewed_at_raw'];
const files = ['01_data_quality.sql', '02_duplicate_answers.sql', '03_sample_composition.sql', '04_score_accuracy.sql', '05_score_direction.sql', '06_largest_disagreements.sql', '07_review_duration.sql'];
const db = new PGlite();
try {
  await db.exec(await readFile(path.join(root, 'sql/00_checks_schema.sql'), 'utf8'));
  await db.exec('BEGIN');
  for (let offset = 0; offset < rows.length; offset += 200) {
    const batch = rows.slice(offset, offset + 200);
    const values = batch.flatMap(row => fields.map(field => row[field] ?? null));
    const placeholders = batch.map((_, rowIndex) => '(' + fields.map((_, fieldIndex) => '$' + (rowIndex * fields.length + fieldIndex + 1)).join(',') + ')');
    await db.query(`INSERT INTO pg_temp.checks (${fields.join(',')}) VALUES ${placeholders.join(',')}`, values);
  }
  await db.exec('COMMIT');
  const detailed = {};
  for (const file of files) detailed[file] = (await db.query(await readFile(path.join(root, 'sql', file), 'utf8'))).rows;
  // Личные ID, сырые комментарии и исходные строки дат хранятся только вне кейса.
  await writeFile(path.join(working, 'detailed-sql-results.json'), JSON.stringify(detailed, null, 2) + '\n');

  const exclusions = (await db.query(`SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE max_points > 0 AND ai_points BETWEEN 0 AND max_points AND curator_points BETWEEN 0 AND max_points) AS score_included,
    COUNT(*) FILTER (WHERE max_points IS NULL OR max_points <= 0) AS invalid_maximum,
    COUNT(*) FILTER (WHERE ai_points IS NULL) AS missing_ai_score,
    COUNT(*) FILTER (WHERE curator_points IS NULL) AS missing_reference,
    COUNT(*) FILTER (WHERE ai_points < 0 OR ai_points > max_points OR curator_points < 0 OR curator_points > max_points) AS invalid_score_range,
    COUNT(*) FILTER (WHERE sent_to_review_at IS NULL OR curator_reviewed_at IS NULL) AS dates_missing_or_invalid,
    COUNT(*) FILTER (WHERE curator_reviewed_at < sent_to_review_at) AS negative_intervals,
    COUNT(*) FILTER (WHERE sent_to_review_at IS NOT NULL AND curator_reviewed_at IS NOT NULL AND curator_reviewed_at >= sent_to_review_at) AS time_included
    FROM pg_temp.checks`)).rows[0];
  const overall = (await db.query(`SELECT COUNT(*) AS compared_answers,
    COUNT(*) FILTER (WHERE ai_points=curator_points) AS exact_matches,
    ROUND(100.0 * COUNT(*) FILTER (WHERE ai_points=curator_points) / NULLIF(COUNT(*),0),2) AS accuracy_pct,
    ROUND(AVG(ABS(ai_points-curator_points)),4) AS mean_absolute_error
    FROM pg_temp.checks WHERE max_points>0 AND ai_points BETWEEN 0 AND max_points AND curator_points BETWEEN 0 AND max_points`)).rows[0];
  const dateRange = (await db.query(`SELECT MIN(sent_to_review_at)::text AS first_sent, MAX(sent_to_review_at)::text AS last_sent,
    MIN(curator_reviewed_at)::text AS first_reviewed, MAX(curator_reviewed_at)::text AS last_reviewed FROM pg_temp.checks`)).rows[0];
  const unique = (await db.query('SELECT COUNT(DISTINCT task_id) AS tasks, COUNT(DISTINCT question_id) AS questions, COUNT(DISTINCT stud_id) AS students FROM pg_temp.checks')).rows[0];
  // Независимые контрольные суммы показателей: расчёт по подготовленным строкам вне SQL.
  const valid = rows.filter(r => r.max_points !== null && Number(r.max_points) > 0 && r.ai_points !== null && r.curator_points !== null && Number(r.ai_points) >= 0 && Number(r.ai_points) <= Number(r.max_points) && Number(r.curator_points) >= 0 && Number(r.curator_points) <= Number(r.max_points));
  assert.equal(Number(overall.compared_answers), valid.length);
  assert.equal(Number(overall.exact_matches), valid.filter(r => Number(r.ai_points) === Number(r.curator_points)).length);
  const absSum = valid.reduce((sum, r) => sum + Math.abs(Number(r.ai_points) - Number(r.curator_points)), 0);
  if (valid.length) assert.ok(Math.abs(Number(overall.mean_absolute_error) - absSum / valid.length) <= 0.000051);
  assert.equal(detailed[files[4]].reduce((sum, row) => sum + Number(row.answers_count), 0), valid.length);
  assert.equal(detailed[files[3]].reduce((sum, row) => sum + Number(row.compared_answers), 0), valid.length);
  assert.equal(Number(exclusions.total), rows.length);
  assert.equal(detailed[files[2]].reduce((sum, row) => sum + Number(row.answers_count), 0), rows.length);
  const measured = rows.filter(r => r.sent_to_review_at !== null && r.curator_reviewed_at !== null && r.curator_reviewed_at >= r.sent_to_review_at);
  assert.equal(Number(exclusions.time_included), measured.length);
  assert.equal(detailed[files[6]].reduce((sum, row) => sum + Number(row.measured_answers), 0), measured.length);
  const caseCounters = new Map();
  const caseSummary = detailed[files[5]].map(row => {
    const position = (caseCounters.get(row.task_number) ?? 0) + 1;
    caseCounters.set(row.task_number, position);
    return { case_label: `CASE-${row.task_number}-${position}`, task_number: row.task_number, ai_points: row.ai_points, curator_points: row.curator_points, score_difference: row.score_difference };
  });
  const report = {
    analyzed_at: new Date().toISOString(),
    source: { ...manifest, source_url: 'https://docs.google.com/spreadsheets/d/1rLxt7ZERF11VZUILCKYxOf7WGRQ0GC2j2mJpLOH1cIg/edit?gid=0', sheet: 'Лист1', snapshot_description: 'Previously retrieved CSV; fixed SHA-256, live sheet not re-read in this run' },
    engine: { name: 'PGlite', version: packageInfo.version, postgres: (await db.query('SELECT version() AS version')).rows[0].version },
    real_dataset_executed: true, application_database_used: false,
    queries_executed: files.length,
    import_and_exclusions: exclusions,
    overall_score_agreement: overall,
    composition: detailed[files[2]], unique_counts: unique,
    score_accuracy: detailed[files[3]], score_direction: detailed[files[4]],
    data_quality: { flagged_rows: detailed[files[0]].length, duplicate_answer_groups: detailed[files[1]].length },
    disagreement_examples: caseSummary,
    review_duration: { status: 'conditional_on_same_timezone_and_event_semantics', values: detailed[files[6]], date_range: dateRange },
    verification: { independent_score_recalculation: 'passed', population_reconciliation: 'passed', pii_and_source_comments_excluded_from_report: true },
    limitations: ['Model version is not provided', 'Timestamp timezone and exact event semantics are not confirmed', 'Curator score treated as reference by owner instruction', 'PredelAI results on the same answers were not supplied', 'Not a representative estimate for all tasks or platform users; task 13 dominates', 'Score agreement does not measure false comments'],
    sources: await Promise.all(['sql/00_checks_schema.sql', ...files.map(f => 'sql/' + f), 'tools/prepare_sql_dataset.py', 'tools/analyze_sql_dataset.mjs'].map(async file => ({ path: file, sha256: digest(await readFile(path.join(root, file))) }))),
  };
  await writeFile(path.join(root, 'verification/dataset-analysis-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ overall, exclusions, composition: report.composition, accuracy: report.score_accuracy, direction: report.score_direction, time: report.review_duration }, null, 2));
} finally {
  await db.close();
}
