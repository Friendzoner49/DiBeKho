-- Two more facts about a customer (customer's request 18/11/2026: the new delivery note template has the cells
-- 'MST 税号' and 'email邮箱'). Customers recorded before stay empty; a note read later fills an empty one in
-- (catalog.upsert_customer), the user edits them in Chi tiết khách hàng.
ALTER TABLE customers ADD COLUMN tax_code TEXT NOT NULL DEFAULT '';
ALTER TABLE customers ADD COLUMN email TEXT NOT NULL DEFAULT '';
