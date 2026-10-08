import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from text2sql_demo.database import create_demo_database, inspect_schema, execute_readonly
from text2sql_demo.pipeline import run_question, select_schema, build_messages
from text2sql_demo.backends import parse_generation, OfflineBackend


class SequenceBackend:
    name = 'test-transport'

    def __init__(self, replies):
        self.replies = iter(replies)

    def generate(self, messages):
        return {'text': next(self.replies), 'input_tokens': 10, 'output_tokens': 5}


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'fixture.sqlite'
        with sqlite3.connect(self.db) as con:
            con.executescript('''
                CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id));
                CREATE TABLE order_items(id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), product_id INTEGER REFERENCES products(id), quantity INTEGER, unit_price INTEGER);
                INSERT INTO customers VALUES(1,'Lan'),(2,'An');
                INSERT INTO products VALUES(1,'A'),(2,'B');
                INSERT INTO orders VALUES(1,1),(2,1);
                INSERT INTO order_items VALUES(1,1,1,2,100),(2,2,2,3,50);
            ''')

    def tearDown(self):
        self.temp.cleanup()

    def test_readonly_aggregate_returns_real_rows(self):
        r = execute_readonly(self.db, 'SELECT SUM(quantity * unit_price) AS total FROM order_items')
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['rows'], [[350]])

    def test_writes_attach_and_pragma_are_denied_and_db_unchanged(self):
        before = self.db.read_bytes()
        for sql in ('DELETE FROM customers', 'DROP TABLE products', "ATTACH ':memory:' AS other", 'PRAGMA user_version = 42', "SELECT load_extension('x')"):
            with self.subTest(sql=sql):
                self.assertEqual(execute_readonly(self.db, sql)['status'], 'error')
        self.assertEqual(before, self.db.read_bytes())

    def test_cte_read_allowed_and_multi_statement_denied(self):
        self.assertEqual(execute_readonly(self.db, 'WITH t AS (SELECT 7 AS n) SELECT n FROM t')['rows'], [[7]])
        self.assertEqual(execute_readonly(self.db, 'SELECT 1; SELECT 2')['status'], 'error')

    def test_timeout_interrupts_expensive_sql(self):
        sql = 'WITH RECURSIVE t(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM t WHERE x<1000000000) SELECT SUM(x) FROM t'
        self.assertEqual(execute_readonly(self.db, sql, timeout_s=0.01)['status'], 'timeout')

    def test_preview_is_capped_without_rewriting_sql(self):
        r = execute_readonly(self.db, 'SELECT id FROM customers ORDER BY id', max_rows=1)
        self.assertEqual(r['rows'], [[1]])
        self.assertTrue(r['truncated'])

    def test_linking_keeps_bridge_between_customer_and_product(self):
        schema = inspect_schema(self.db)
        selected = select_schema(schema, 'Khách hàng mua sản phẩm nào?', True)
        self.assertEqual(set(selected), {'customers', 'products', 'orders', 'order_items'})

    def test_prompt_has_question_schema_and_no_answer_sql_for_target(self):
        messages = build_messages('Câu hỏi mới 123', inspect_schema(self.db), [], True)
        prompt = '\n'.join(m['content'] for m in messages)
        self.assertIn('Câu hỏi mới 123', prompt)
        self.assertIn('CREATE TABLE', prompt)
        self.assertNotIn('gold_sql', prompt)

    def test_repair_uses_error_feedback_and_corrects_real_query(self):
        backend = SequenceBackend(['{"sql":"SELECT missing FROM customers"}', '{"sql":"SELECT name FROM customers ORDER BY id"}'])
        r = run_question(self.db, 'Danh sách khách hàng', backend, few_shot=False, linking=False, repair=True)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['execution']['rows'], [['Lan'], ['An']])
        self.assertEqual(len(r['attempts']), 2)
        self.assertIn('no such column', r['attempts'][0]['execution']['error'])

    def test_repair_stops_after_two_corrections(self):
        backend = SequenceBackend(['{"sql":"SELECT bad1 FROM customers"}', '{"sql":"SELECT bad2 FROM customers"}', '{"sql":"SELECT bad3 FROM customers"}'])
        r = run_question(self.db, 'Danh sách khách hàng', backend, repair=True)
        self.assertEqual(r['status'], 'error')
        self.assertEqual(len(r['attempts']), 3)

    def test_successful_empty_result_is_not_repaired(self):
        backend = SequenceBackend(['{"sql":"SELECT name FROM customers WHERE id=99"}'])
        r = run_question(self.db, 'Khách 99', backend, repair=True)
        self.assertEqual(r['execution']['rows'], [])
        self.assertEqual(len(r['attempts']), 1)

    def test_linking_does_not_add_demos_that_reference_missing_tables(self):
        backend = SequenceBackend(['{"sql":"SELECT COUNT(*) FROM orders"}'])
        r = run_question(self.db, 'Có bao nhiêu đơn hàng theo từng trạng thái?', backend, linking=True, few_shot=True)
        self.assertEqual(r['selected_tables'], ['orders'])
        self.assertEqual(r['examples'], [])

    def test_each_attempt_exposes_actual_prompt_including_repair_feedback(self):
        backend = SequenceBackend(['{"sql":"SELECT missing FROM customers"}', '{"sql":"SELECT name FROM customers"}'])
        r = run_question(self.db, 'Danh sách khách hàng', backend, linking=True, repair=True)
        prompts = r['attempts'][1]['messages']
        self.assertIn('no such column', prompts[-1]['content'])
        self.assertIn('CREATE TABLE products', prompts[0]['content'])

    def test_large_scalar_blob_allocation_is_denied(self):
        r = execute_readonly(self.db, 'SELECT length(randomblob(10000000))', timeout_s=0.001)
        self.assertEqual(r['status'], 'error')

    def test_model_json_and_fenced_sql_parse_without_changing_literals(self):
        sql = "SELECT 'a; b' AS value"
        self.assertEqual(parse_generation(json.dumps({'sql': sql}))['sql'], sql)
        self.assertEqual(parse_generation('```sql\nSELECT 42\n```')['sql'], 'SELECT 42')
        with self.assertRaises(ValueError):
            parse_generation('{"sql":42}')

    def test_offline_rejects_unknown_question_instead_of_guessing(self):
        backend = OfflineBackend()
        with self.assertRaises(ValueError):
            backend.generate([{'role': 'user', 'content': 'Câu hỏi không có trong bộ ví dụ'}])

    def test_demo_creation_is_deterministic_and_not_overwrite_existing(self):
        a = Path(self.temp.name) / 'demo_a.sqlite'
        b = Path(self.temp.name) / 'demo_b.sqlite'
        create_demo_database(a)
        create_demo_database(b)
        query = 'SELECT COUNT(*), SUM(quantity * unit_price) FROM order_items'
        self.assertEqual(execute_readonly(a, query)['rows'], execute_readonly(b, query)['rows'])
        before = a.read_bytes()
        create_demo_database(a)
        self.assertEqual(before, a.read_bytes())


if __name__ == '__main__':
    unittest.main()
