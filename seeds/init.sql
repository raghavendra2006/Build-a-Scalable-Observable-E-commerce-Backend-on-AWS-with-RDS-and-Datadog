-- Seed script for the e-commerce database
-- Runs automatically on first start of the db container

CREATE TABLE IF NOT EXISTS products (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255)   NOT NULL,
    description TEXT,
    price       NUMERIC(10,2)  NOT NULL,
    category    VARCHAR(100),
    stock       INTEGER        NOT NULL DEFAULT 0,
    created_at  TIMESTAMP      NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL PRIMARY KEY,
    product_id  INTEGER        NOT NULL REFERENCES products(id),
    quantity    INTEGER        NOT NULL DEFAULT 1,
    created_at  TIMESTAMP      NOT NULL DEFAULT NOW()
);

INSERT INTO products (name, description, price, category, stock) VALUES
  ('Wireless Mouse',              'Ergonomic wireless mouse with USB-C receiver',            29.99,  'Electronics',  500),
  ('Mechanical Keyboard',         'RGB mechanical keyboard with Cherry MX switches',          89.99,  'Electronics',  300),
  ('USB-C Hub',                   '7-in-1 USB-C hub with HDMI, SD card, and Ethernet',       49.99,  'Electronics',  200),
  ('Noise-Cancelling Headphones', 'Over-ear headphones with active noise cancellation',      149.99,  'Electronics',  150),
  ('Laptop Stand',                'Adjustable aluminium laptop stand',                        39.99,  'Accessories',  400),
  ('Webcam HD 1080p',             'Full HD webcam with built-in microphone',                  59.99,  'Electronics',  250),
  ('Monitor Light Bar',           'LED monitor light bar with adjustable colour temperature', 34.99,  'Accessories',  350),
  ('Desk Mat XL',                 'Extra-large desk mat, 900x400 mm, water-resistant',        24.99,  'Accessories',  600),
  ('Portable SSD 1TB',            '1 TB portable SSD with USB 3.2 Gen 2',                    99.99,  'Storage',      180),
  ('Smart Power Strip',           'Wi-Fi enabled power strip with 4 outlets and USB ports',   27.99,  'Smart Home',   320),
  ('Ergonomic Chair Cushion',     'Memory-foam seat cushion for office chairs',               44.99,  'Furniture',    220),
  ('Cable Management Kit',        '120-piece cable management kit with clips and ties',       15.99,  'Accessories',  700),
  ('Blue-Light Glasses',          'Anti-blue-light glasses for screen use',                   19.99,  'Accessories',  450),
  ('Wireless Charger Pad',        '15 W Qi wireless charging pad',                           22.99,  'Electronics',  380),
  ('Reusable Water Bottle',       '750 ml insulated stainless-steel water bottle',            18.99,  'Lifestyle',    550)
ON CONFLICT DO NOTHING;
