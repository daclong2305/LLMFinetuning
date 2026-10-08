"""Fixed teaching examples; excluded when identical to the target question."""
EXAMPLES = [
    {'question':'Top 5 sản phẩm có doanh thu cao nhất', 'sql':"SELECT p.name AS san_pham, SUM(i.quantity * i.unit_price) AS doanh_thu FROM products p JOIN order_items i ON i.product_id=p.id JOIN orders o ON o.id=i.order_id WHERE o.status='completed' GROUP BY p.id, p.name ORDER BY doanh_thu DESC, p.id LIMIT 5"},
    {'question':'Tổng doanh thu năm 2025 là bao nhiêu?', 'sql':"SELECT SUM(i.quantity * i.unit_price) AS doanh_thu FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.status='completed' AND o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01'"},
    {'question':'Có bao nhiêu đơn hàng theo từng trạng thái?', 'sql':'SELECT status AS trang_thai, COUNT(*) AS so_don FROM orders GROUP BY status ORDER BY so_don DESC, status'},
    {'question':'Khách hàng nào chưa từng đặt hàng?', 'sql':'SELECT c.name AS khach_hang, c.city AS thanh_pho FROM customers c LEFT JOIN orders o ON o.customer_id=c.id WHERE o.id IS NULL ORDER BY c.id'},
    {'question':'Doanh thu theo từng tháng năm 2025', 'sql':"SELECT substr(o.order_date,1,7) AS thang, SUM(i.quantity * i.unit_price) AS doanh_thu FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.status='completed' AND o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01' GROUP BY substr(o.order_date,1,7) ORDER BY thang"},
    {'question':'Top 5 khách hàng có tổng chi tiêu cao nhất', 'sql':"SELECT c.name AS khach_hang, SUM(i.quantity*i.unit_price) AS chi_tieu FROM customers c JOIN orders o ON o.customer_id=c.id JOIN order_items i ON i.order_id=o.id WHERE o.status='completed' GROUP BY c.id,c.name ORDER BY chi_tieu DESC,c.id LIMIT 5"},
]
