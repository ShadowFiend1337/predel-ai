// Проверка SQL на синтетических данных в PostgreSQL-движке PGlite в памяти.
// node tools/verify_sql.mjs /tmp/predel-sql-validation
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dependencyRoot = process.argv[2];
if (!dependencyRoot) throw new Error('Укажите каталог временной установки @electric-sql/pglite');
const require = createRequire(path.join(path.resolve(dependencyRoot), 'package.json'));
const { PGlite } = require('@electric-sql/pglite');
const packageInfo = JSON.parse(await readFile(path.join(dependencyRoot, 'node_modules/@electric-sql/pglite/package.json'), 'utf8'));
const db = new PGlite();
const files = (await readdir(path.join(root, 'sql'))).filter(name => /^0[1-7]_.*\.sql$/.test(name)).sort();
assert.equal(files.length, 7);
const statements = await Promise.all(files.map(name => readFile(path.join(root, 'sql', name), 'utf8')));
const query = async number => (await db.query(statements[number - 1])).rows;
const checks = [];

async function check(name, operation) {
  await operation();
  checks.push({ name, status: 'passed' });
}

async function temporaryChange(sql, operation) {
  await db.exec('BEGIN');
  try {
    await db.exec(sql);
    await operation();
  } finally {
    await db.exec('ROLLBACK');
  }
}

try {
  await db.exec(await readFile(path.join(root, 'sql/00_checks_schema.sql'), 'utf8'));
  await db.exec(await readFile(path.join(root, 'sql/fixtures/synthetic_checks.sql'), 'utf8'));
  const baseResults = await Promise.all(files.map((_, i) => query(i + 1)));
  await check('01: корректные данные не дают замечаний', async () => assert.deepEqual(baseResults[0], []));
  await check('02: уникальные ответы не считаются дублями', async () => assert.deepEqual(baseResults[1], []));
  await check('03: состав выборки', async () => {
    assert.deepEqual(baseResults[2].map(r => [r.task_number, Number(r.answers_count), Number(r.tasks_count), Number(r.students_count)]), [[13, 5, 2, 5], [14, 3, 1, 3]]);
  });
  await check('04: точность, знаменатель и абсолютное отклонение', async () => {
    assert.deepEqual(baseResults[3].map(r => [r.task_number, Number(r.compared_answers), Number(r.exact_matches), Number(r.accuracy_pct), Number(r.mean_absolute_error)]), [[13, 5, 1, 20, 1.2], [14, 3, 1, 33.33, 2]]);
  });
  await check('05: направление расхождения и доли', async () => {
    const expected = { 'Совпадение': [2, 25], 'Завышение': [3, 37.5], 'Занижение': [3, 37.5] };
    assert.equal(baseResults[4].length, 3);
    for (const row of baseResults[4]) assert.deepEqual([Number(row.answers_count), Number(row.share_pct)], expected[row.result]);
  });
  await check('06: не более трёх расхождений каждого номера и порядок при равных разницах', async () => {
    assert.deepEqual(baseResults[5].map(r => r.answer_id), ['demo-a4', 'demo-a5', 'demo-a2', 'demo-a7', 'demo-a8']);
  });
  await check('07: среднее, медиана и интерполированный P90', async () => {
    assert.deepEqual(baseResults[6].map(r => [r.task_number, Number(r.measured_answers), Number(r.average_hours), Number(r.median_hours), Number(r.p90_hours)]), [[13, 5, 5, 5, 8.2], [14, 3, 4, 4, 5.6]]);
  });
  for (const [name, patch] of [
    ['Нет оценки ИИ', 'ai_points = NULL'],
    ['Нет эталона', 'curator_points = NULL'],
    ['Оценка выше максимума', 'ai_points = 3'],
    ['Оценка ниже нуля', 'ai_points = -1'],
    ['Эталон выше максимума', 'curator_points = 3'],
    ['Максимум отсутствует', 'max_points = NULL'],
    ['Максимум равен нулю', 'max_points = 0'],
  ]) {
    await check(name + ': дефект виден, сравнение исключено, время сохранено', async () => temporaryChange(`UPDATE pg_temp.checks SET ${patch} WHERE answer_id = 'demo-a1'`, async () => {
      assert.deepEqual((await query(1)).map(r => r.answer_id), ['demo-a1']);
      assert.equal(Number((await query(4))[0].compared_answers), 4);
      assert.equal((await query(5)).reduce((sum, r) => sum + Number(r.answers_count), 0), 7);
      assert.equal(Number((await query(7))[0].measured_answers), 5);
    }));
  }
  for (const [name, patch] of [
    ['Неразобранная дата', "sent_to_review_at = NULL, sent_to_review_at_raw = 'Синтетическое некорректное значение'"],
    ['Нет даты куратора', 'curator_reviewed_at = NULL'],
    ['Отрицательный интервал', "curator_reviewed_at = '2026-09-01 09:00:00'"],
  ]) {
    await check(name + ': время исключено, сравнение баллов сохранено', async () => temporaryChange(`UPDATE pg_temp.checks SET ${patch} WHERE answer_id = 'demo-a1'`, async () => {
      assert.deepEqual((await query(1)).map(r => r.answer_id), ['demo-a1']);
      assert.equal(Number((await query(7))[0].measured_answers), 4);
      assert.deepEqual(await query(4), baseResults[3]);
    }));
  }
  await check('Повторный ID обнаружен; автоматического удаления дубля нет', async () => temporaryChange("INSERT INTO pg_temp.checks SELECT * FROM pg_temp.checks WHERE answer_id = 'demo-a1'", async () => {
    const duplicates = await query(2);
    assert.equal(duplicates.length, 1);
    assert.equal(duplicates[0].answer_id, 'demo-a1');
    assert.equal(Number(duplicates[0].rows_count), 2);
    assert.equal(Number((await query(3))[0].answers_count), 6);
  }));
  await check('Пробельный ID обнаружен как пропуск', async () => temporaryChange("UPDATE pg_temp.checks SET answer_id = '   ' WHERE source_row = 1", async () => {
    assert.deepEqual((await query(1)).map(r => r.source_row), [1]);
    assert.deepEqual(await query(2), []);
  }));
  await check('Одна работа: процентили определены, расхождений нет', async () => temporaryChange("DELETE FROM pg_temp.checks WHERE answer_id <> 'demo-a1'", async () => {
    const row = (await query(7))[0];
    assert.deepEqual([Number(row.average_hours), Number(row.median_hours), Number(row.p90_hours)], [1, 1, 1]);
    assert.equal(Number((await query(4))[0].accuracy_pct), 100);
    assert.deepEqual(await query(6), []);
  }));
  await check('Пустой набор: семь запросов возвращают пустые результаты', async () => temporaryChange('TRUNCATE pg_temp.checks', async () => {
    for (let number = 1; number <= 7; number++) assert.deepEqual(await query(number), []);
  }));
  const sources = ['sql/00_checks_schema.sql', 'sql/fixtures/synthetic_checks.sql', ...files.map(name => 'sql/' + name), 'tools/verify_sql.mjs'];
  const report = {
    checked_at: new Date().toISOString(),
    engine: { name: 'PGlite', version: packageInfo.version, postgres: (await db.query('SELECT version() AS version')).rows[0].version },
    dataset: '8 synthetic records; additional isolated boundary checks rolled back',
    real_dataset_executed: false,
    application_database_used: false,
    queries_passed: files.length,
    verification_scenarios_passed: checks.length,
    failures: 0,
    checks,
    base_results: Object.fromEntries(files.map((file, index) => [file, baseResults[index]])),
    sources: await Promise.all(sources.map(async file => ({ path: file, sha256: createHash('sha256').update(await readFile(path.join(root, file))).digest('hex') }))),
  };
  await writeFile(path.join(root, 'verification/sql-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ queries_passed: files.length, verification_scenarios_passed: checks.length, real_dataset_executed: false }));
} finally {
  await db.close();
}
