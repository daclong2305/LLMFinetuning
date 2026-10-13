-- Synthetic teaching data. Names, locations and measurements are fictional.
-- This is not the original ViText2SQL/Spider database.
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE __visql_demo (description TEXT NOT NULL);
INSERT INTO __visql_demo VALUES ('Dữ liệu mô phỏng để demo ViSQL; không dùng làm điểm benchmark ViText2SQL gốc.');

CREATE TABLE "kiến trúc sư" (
    "id" TEXT PRIMARY KEY,
    "tên" TEXT,
    "quốc tịch" TEXT,
    "giới tính" TEXT
);
CREATE TABLE "cầu" (
    "id kiến trúc sư" NUMERIC REFERENCES "kiến trúc sư" ("id"),
    "id" NUMERIC PRIMARY KEY,
    "tên" TEXT,
    "địa điểm" TEXT,
    "chiều dài theo mét" NUMERIC,
    "chiều dài theo feet" NUMERIC
);
CREATE TABLE "nhà máy" (
    "id kiến trúc sư" NUMERIC REFERENCES "kiến trúc sư" ("id"),
    "id" NUMERIC PRIMARY KEY,
    "địa điểm" TEXT,
    "tên" TEXT,
    "loại" TEXT,
    "năm xây dựng" NUMERIC,
    "ghi chú" TEXT
);

INSERT INTO "kiến trúc sư" VALUES
('1', 'Nguyễn Minh An', 'Vietnamese', 'female'),
('2', 'Trần Quốc Bình', 'Vietnamese', 'male'),
('3', 'Lê Thu Chi', 'Canadian', 'female'),
('4', 'Phạm Hoàng Dũng', 'American', 'male'),
('5', 'Võ Ngọc Hà', 'French', 'female'),
('6', 'Đỗ Thành Nam', 'Belgian', 'male'),
('7', 'Bùi Thanh Lan', 'American', 'female'),
('8', 'Hoàng Đức Minh', 'Canadian', 'male');

INSERT INTO "cầu" VALUES
(1, 1, 'Cầu Bình Minh', 'Hà Nội', 120, 393.70),
(1, 2, 'Cầu Sông Xanh', 'Đà Nẵng', 250, 820.21),
(1, 3, 'Cầu Hoa Sen', 'Cần Thơ', 85, 278.87),
(2, 4, 'Cầu Ánh Dương', 'Huế', 75, 246.06),
(2, 5, 'Cầu An Hòa', 'Hội An', 60, 196.85),
(3, 6, 'Cầu Lá Phong', 'Toronto', 310, 1017.06),
(4, 7, 'Kolob Arch', 'Utah', 90, 295.28),
(4, 8, 'Rainbow Bridge', 'Arizona', 88, 288.71),
(5, 9, 'Cầu Mùa Xuân', 'Lyon', 140, 459.32),
(6, 10, 'Cầu Gió Nhẹ', 'Brussels', 55, 180.45),
(7, 11, 'Cầu Chân Trời', 'Seattle', 420, 1377.95),
(8, 12, 'Cầu Bắc Sơn', 'Vancouver', 185, 606.96);

INSERT INTO "nhà máy" VALUES
(1, 1, 'Hà Nội', 'Moulin Hoa Sen', 'Grondzeiler', 1820, 'Bản ghi mô phỏng'),
(1, 2, 'Nam Định', 'Nhà máy An Bình', 'Beltmolen', 1905, 'Bản ghi mô phỏng'),
(1, 3, 'Ninh Bình', 'Moulin Sông Xanh', 'Grondzeiler', 1880, 'Bản ghi mô phỏng'),
(2, 4, 'Huế', 'Nhà máy Ánh Dương', 'Watermill', 1930, 'Bản ghi mô phỏng'),
(3, 5, 'Toronto', 'Moulin Lá Phong', 'Grondzeiler', 1840, 'Bản ghi mô phỏng'),
(4, 6, 'Seattle', 'Nhà máy Chân Trời', 'Beltmolen', 1920, 'Bản ghi mô phỏng'),
(5, 7, 'Lyon', 'Moulin Mùa Xuân', 'Watermill', 1810, 'Bản ghi mô phỏng'),
(6, 8, 'Donceel', 'Moulin Gió Nhẹ', 'Grondzeiler', 1790, 'Bản ghi mô phỏng'),
(7, 9, 'Portland', 'Nhà máy Thanh Lan', 'Grondzeiler', 1950, 'Bản ghi mô phỏng'),
(4, 10, 'Boston', 'Moulin Đại Dương', 'Watermill', 1875, 'Bản ghi mô phỏng');
COMMIT;
