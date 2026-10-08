"""Deterministic synthetic data and bounded, read-only SQLite execution."""
import random
import sqlite3
import time
from contextlib import closing
from pathlib import Path


DESCRIPTIONS = {
    'customers': 'Khách hàng: name là tên; city là thành phố.',
    'products': 'Sản phẩm và danh mục category.',
    'orders': 'Đơn hàng: order_date dạng YYYY-MM-DD; status là completed, pending hoặc cancelled.',
    'order_items': 'Chi tiết đơn: quantity * unit_price là doanh thu dòng, đơn vị VND. Doanh thu chỉ tính đơn completed.',
}


def create_demo_database(path):
    path = Path(path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT NOT NULL);
            CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL);
            CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), order_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('completed','pending','cancelled')));
            CREATE TABLE order_items(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL, unit_price INTEGER NOT NULL);
        ''')
        names = ['Nguyễn An','Trần Bình','Lê Chi','Phạm Dũng','Hoàng Hà','Võ Lan','Đỗ Minh','Bùi Ngọc']
        cities = ['Hà Nội', 'TP.HCM', 'Đà Nẵng', 'Cần Thơ']
        con.executemany('INSERT INTO customers VALUES(?,?,?)', [(i, names[(i-1)%8] + (f' {i}' if i>8 else ''), cities[(i-1)%4]) for i in range(1,33)])
        products = [('Laptop văn phòng','Điện tử',15000000), ('Tai nghe','Điện tử',750000), ('Bàn phím','Điện tử',550000), ('Chuột không dây','Điện tử',300000), ('Balo','Phụ kiện',450000), ('Bình giữ nhiệt','Phụ kiện',250000), ('Sổ tay','Văn phòng phẩm',60000), ('Bút','Văn phòng phẩm',15000), ('Đèn bàn','Gia dụng',400000), ('Ấm siêu tốc','Gia dụng',600000), ('Áo thun','Thời trang',220000), ('Giày thể thao','Thời trang',850000)]
        con.executemany('INSERT INTO products VALUES(?,?,?)', [(i,n,c) for i,(n,c,p) in enumerate(products,1)])
        item_id = 1
        for i in range(1,145):
            date = f'2025-{(i-1)%12+1:02d}-{(i*7)%27+1:02d}'
            status = 'cancelled' if i%9==0 else 'pending' if i%7==0 else 'completed'
            con.execute('INSERT INTO orders VALUES(?,?,?,?)', (i,rng.randint(1,28),date,status))
            for product_id in rng.sample(range(1,13),rng.randint(1,4)):
                con.execute('INSERT INTO order_items VALUES(?,?,?,?,?)', (item_id,i,product_id,rng.randint(1,4),products[product_id-1][2]))
                item_id += 1


def inspect_schema(path):
    schema = {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as con:
        for name, ddl in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            schema[name] = {'ddl': ddl, 'description': DESCRIPTIONS.get(name,''),
                            'columns': [{'name': r[1], 'type': r[2], 'pk': bool(r[5])} for r in con.execute(f'PRAGMA table_info("{name}")')],
                            'foreign_keys': [{'table': r[2], 'from': r[3], 'to': r[4]} for r in con.execute(f'PRAGMA foreign_key_list("{name}")')]}
    return schema


def execute_readonly(path, sql, timeout_s=5, max_rows=200):
    started = time.perf_counter()
    result = {'status':'error', 'columns':[], 'rows':[], 'truncated':False, 'error':None}
    if not isinstance(sql,str) or not sql.strip() or len(sql)>20000:
        result['error'] = 'SQL rỗng hoặc quá dài.'
        result['duration_ms'] = 0
        return result
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

    def authorize(action, arg1, arg2, database, source):
        if action not in allowed:
            return sqlite3.SQLITE_DENY
        if action==sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in {'load_extension','readfile','writefile','eval','randomblob','zeroblob','printf','format'}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as con:
            con.execute('PRAGMA query_only=ON')
            if hasattr(con,'setlimit'):
                con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1024*1024)
                con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,20000)
            con.enable_load_extension(False)
            con.set_authorizer(authorize)
            con.set_progress_handler(lambda: int(time.perf_counter()-started>timeout_s),1000)
            cursor = con.execute(sql)
            result['columns'] = [c[0] for c in cursor.description or []]
            rows = cursor.fetchmany(max_rows+1)
            preview = [[v.hex() if isinstance(v,bytes) else v for v in row] for row in rows[:max_rows]]
            if any(isinstance(v,str) and len(v)>100000 for row in preview for v in row):
                raise sqlite3.DataError('Một ô kết quả vượt giới hạn preview 100.000 ký tự.')
            result.update(status='ok', rows=preview, truncated=len(rows)>max_rows)
    except (sqlite3.Error, sqlite3.Warning) as exc:
        result['status'] = 'timeout' if 'interrupted' in str(exc) else 'error'
        result['error'] = str(exc)
    finally:
        result['duration_ms'] = round((time.perf_counter()-started)*1000,2)
    return result
