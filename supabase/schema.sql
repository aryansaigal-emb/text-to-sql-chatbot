-- Run this in the Supabase SQL editor.
-- The backend also creates app_chat_* tables on startup, but this file is handy for review.

create table if not exists app_chat_sessions (
  id uuid primary key,
  title text not null default 'New analysis',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists app_chat_messages (
  id bigserial primary key,
  session_id uuid not null references app_chat_sessions(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  sql text,
  rows_json jsonb,
  created_at timestamptz not null default now()
);

-- Demo data for testing Text-to-SQL.
create table if not exists customers (
  id bigserial primary key,
  name text not null,
  industry text not null default 'General',
  region text not null,
  country text not null default 'Unknown',
  plan text not null,
  account_owner text not null default 'Unassigned',
  health_score integer not null default 80,
  created_at date not null default current_date,
  constraint customers_name_key unique (name)
);

alter table customers add column if not exists industry text not null default 'General';
alter table customers add column if not exists country text not null default 'Unknown';
alter table customers add column if not exists account_owner text not null default 'Unassigned';
alter table customers add column if not exists health_score integer not null default 80;

create table if not exists orders (
  id bigserial primary key,
  customer_id bigint not null references customers(id),
  status text not null,
  channel text not null default 'sales',
  amount numeric(12, 2) not null,
  ordered_at date not null default current_date,
  constraint orders_demo_unique unique (customer_id, status, amount, ordered_at)
);

alter table orders add column if not exists channel text not null default 'sales';

create table if not exists products (
  id bigserial primary key,
  sku text not null unique,
  name text not null,
  category text not null,
  unit_price numeric(12, 2) not null,
  active boolean not null default true
);

create table if not exists order_items (
  id bigserial primary key,
  order_id bigint not null references orders(id) on delete cascade,
  product_id bigint not null references products(id),
  quantity integer not null,
  unit_price numeric(12, 2) not null,
  discount_pct numeric(5, 2) not null default 0
);

create table if not exists support_tickets (
  id bigserial primary key,
  customer_id bigint not null references customers(id),
  priority text not null,
  status text not null,
  issue_type text not null,
  satisfaction_score integer,
  opened_at date not null,
  closed_at date
);

create table if not exists subscriptions (
  id bigserial primary key,
  customer_id bigint not null references customers(id),
  plan text not null,
  monthly_recurring_revenue numeric(12, 2) not null,
  started_at date not null,
  churned_at date
);

delete from orders
where customer_id in (
  select id from customers
  where name in (
    'Acme Finance', 'Bluebird Retail', 'Crescent Labs', 'Nimbus Health',
    'Vertex Logistics', 'Aurora Foods', 'Summit Education', 'Helio Energy',
    'PixelCraft Studio', 'MetroBank Digital', 'GreenLeaf Supply', 'Orbit Travel'
  )
);

delete from customers
where name in (
  'Acme Finance', 'Bluebird Retail', 'Crescent Labs', 'Nimbus Health',
  'Vertex Logistics', 'Aurora Foods', 'Summit Education', 'Helio Energy',
  'PixelCraft Studio', 'MetroBank Digital', 'GreenLeaf Supply', 'Orbit Travel'
);

truncate table order_items restart identity cascade;
truncate table products restart identity cascade;
truncate table support_tickets restart identity cascade;
truncate table subscriptions restart identity cascade;

insert into customers (name, industry, region, country, plan, account_owner, health_score, created_at)
values
  ('Acme Finance', 'Finance', 'North America', 'United States', 'Enterprise', 'Maya', 91, '2026-01-12'),
  ('Bluebird Retail', 'Retail', 'Europe', 'United Kingdom', 'Growth', 'Noah', 73, '2026-02-02'),
  ('Crescent Labs', 'Biotech', 'Asia', 'India', 'Enterprise', 'Isha', 88, '2026-03-19'),
  ('Nimbus Health', 'Healthcare', 'North America', 'Canada', 'Growth', 'Maya', 82, '2026-01-29'),
  ('Vertex Logistics', 'Logistics', 'Europe', 'Germany', 'Enterprise', 'Noah', 68, '2026-02-14'),
  ('Aurora Foods', 'Food', 'Asia', 'Singapore', 'Starter', 'Isha', 76, '2026-03-08'),
  ('Summit Education', 'Education', 'North America', 'United States', 'Growth', 'Maya', 84, '2026-03-21'),
  ('Helio Energy', 'Energy', 'Europe', 'France', 'Enterprise', 'Noah', 94, '2026-04-03'),
  ('PixelCraft Studio', 'Media', 'Asia', 'Japan', 'Starter', 'Isha', 61, '2026-04-11'),
  ('MetroBank Digital', 'Finance', 'Europe', 'Netherlands', 'Enterprise', 'Noah', 89, '2026-04-18'),
  ('GreenLeaf Supply', 'Manufacturing', 'North America', 'Mexico', 'Growth', 'Maya', 79, '2026-04-22'),
  ('Orbit Travel', 'Travel', 'Asia', 'UAE', 'Growth', 'Isha', 72, '2026-05-01')
on conflict do nothing;

insert into products (sku, name, category, unit_price, active)
values
  ('ANL-BASE', 'Analytics Base', 'Analytics', 1200.00, true),
  ('ANL-PRO', 'Analytics Pro', 'Analytics', 3200.00, true),
  ('AI-COPILOT', 'AI Copilot', 'AI', 4500.00, true),
  ('DATA-SYNC', 'Data Sync', 'Integration', 2100.00, true),
  ('SEC-AUDIT', 'Security Audit', 'Services', 3800.00, true),
  ('SUPPORT-PLUS', 'Support Plus', 'Support', 900.00, true)
on conflict do nothing;

insert into orders (customer_id, status, channel, amount, ordered_at)
select c.id, o.status, o.channel, o.amount, o.ordered_at::date
from customers c
join (
  values
    ('Acme Finance', 'paid', 'sales', 12400.00, '2026-04-01'),
    ('Acme Finance', 'paid', 'partner', 8500.00, '2026-04-19'),
    ('Bluebird Retail', 'pending', 'self-serve', 2100.00, '2026-04-23'),
    ('Crescent Labs', 'paid', 'sales', 17800.00, '2026-05-02'),
    ('Nimbus Health', 'paid', 'sales', 9600.00, '2026-03-17'),
    ('Vertex Logistics', 'overdue', 'partner', 14200.00, '2026-04-05'),
    ('Aurora Foods', 'paid', 'self-serve', 1800.00, '2026-04-29'),
    ('Summit Education', 'paid', 'sales', 7200.00, '2026-05-03'),
    ('Helio Energy', 'paid', 'sales', 22600.00, '2026-05-04'),
    ('PixelCraft Studio', 'pending', 'self-serve', 1600.00, '2026-05-05'),
    ('MetroBank Digital', 'paid', 'partner', 19800.00, '2026-05-06'),
    ('GreenLeaf Supply', 'paid', 'sales', 6400.00, '2026-05-07'),
    ('Orbit Travel', 'cancelled', 'self-serve', 3200.00, '2026-05-08')
) as o(customer_name, status, channel, amount, ordered_at)
on o.customer_name = c.name
on conflict do nothing;

insert into order_items (order_id, product_id, quantity, unit_price, discount_pct)
select o.id, p.id, item.quantity, item.unit_price, item.discount_pct
from orders o
join customers c on c.id = o.customer_id
join (
  values
    ('Acme Finance', '2026-04-01', 'ANL-PRO', 2, 3200.00, 5.00),
    ('Acme Finance', '2026-04-01', 'AI-COPILOT', 1, 4500.00, 0.00),
    ('Acme Finance', '2026-04-19', 'SEC-AUDIT', 1, 3800.00, 0.00),
    ('Bluebird Retail', '2026-04-23', 'DATA-SYNC', 1, 2100.00, 0.00),
    ('Crescent Labs', '2026-05-02', 'AI-COPILOT', 3, 4500.00, 10.00),
    ('Nimbus Health', '2026-03-17', 'ANL-BASE', 4, 1200.00, 0.00),
    ('Vertex Logistics', '2026-04-05', 'DATA-SYNC', 5, 2100.00, 5.00),
    ('Aurora Foods', '2026-04-29', 'SUPPORT-PLUS', 2, 900.00, 0.00),
    ('Summit Education', '2026-05-03', 'ANL-PRO', 2, 3200.00, 0.00),
    ('Helio Energy', '2026-05-04', 'AI-COPILOT', 4, 4500.00, 5.00),
    ('MetroBank Digital', '2026-05-06', 'SEC-AUDIT', 3, 3800.00, 0.00),
    ('GreenLeaf Supply', '2026-05-07', 'DATA-SYNC', 3, 2100.00, 0.00),
    ('Orbit Travel', '2026-05-08', 'ANL-BASE', 2, 1200.00, 0.00)
) as item(customer_name, ordered_at, sku, quantity, unit_price, discount_pct)
on item.customer_name = c.name and item.ordered_at::date = o.ordered_at
join products p on p.sku = item.sku;

insert into subscriptions (customer_id, plan, monthly_recurring_revenue, started_at, churned_at)
select c.id, s.plan, s.mrr, s.started_at::date, s.churned_at::date
from customers c
join (
  values
    ('Acme Finance', 'Enterprise', 5200.00, '2026-01-12', null),
    ('Bluebird Retail', 'Growth', 1450.00, '2026-02-02', null),
    ('Crescent Labs', 'Enterprise', 6100.00, '2026-03-19', null),
    ('Nimbus Health', 'Growth', 2300.00, '2026-01-29', null),
    ('Vertex Logistics', 'Enterprise', 4800.00, '2026-02-14', null),
    ('Aurora Foods', 'Starter', 700.00, '2026-03-08', null),
    ('Summit Education', 'Growth', 2600.00, '2026-03-21', null),
    ('Helio Energy', 'Enterprise', 7400.00, '2026-04-03', null),
    ('PixelCraft Studio', 'Starter', 650.00, '2026-04-11', '2026-05-09'),
    ('MetroBank Digital', 'Enterprise', 6900.00, '2026-04-18', null),
    ('GreenLeaf Supply', 'Growth', 2100.00, '2026-04-22', null),
    ('Orbit Travel', 'Growth', 1900.00, '2026-05-01', null)
) as s(customer_name, plan, mrr, started_at, churned_at)
on s.customer_name = c.name;

insert into support_tickets (customer_id, priority, status, issue_type, satisfaction_score, opened_at, closed_at)
select c.id, t.priority, t.status, t.issue_type, t.satisfaction_score, t.opened_at::date, t.closed_at::date
from customers c
join (
  values
    ('Acme Finance', 'high', 'closed', 'billing', 5, '2026-04-02', '2026-04-03'),
    ('Bluebird Retail', 'medium', 'open', 'integration', null, '2026-05-01', null),
    ('Crescent Labs', 'low', 'closed', 'usage', 4, '2026-05-04', '2026-05-05'),
    ('Vertex Logistics', 'urgent', 'open', 'security', null, '2026-05-06', null),
    ('Helio Energy', 'medium', 'closed', 'reporting', 5, '2026-05-05', '2026-05-07'),
    ('PixelCraft Studio', 'high', 'open', 'billing', null, '2026-05-08', null),
    ('Orbit Travel', 'medium', 'closed', 'onboarding', 3, '2026-05-03', '2026-05-04')
) as t(customer_name, priority, status, issue_type, satisfaction_score, opened_at, closed_at)
on t.customer_name = c.name;
