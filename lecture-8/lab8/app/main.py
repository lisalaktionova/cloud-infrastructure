import asyncio
import os
import random
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# Адреса БД из env
PRIMARY_DSN = os.getenv(
    "PRIMARY_DSN",
    "postgresql://appuser:apppassword@postgres-primary:5432/shopdb",
)
STANDBY_DSN = os.getenv(
    "STANDBY_DSN",
    "postgresql://appuser:apppassword@postgres-standby:5432/shopdb",
)

primary_pool: asyncpg.Pool | None = None
standby_pool: asyncpg.Pool | None = None

app = FastAPI(title="shop-app")


@app.on_event("startup")
async def startup():
    global primary_pool, standby_pool
    primary_pool = await asyncpg.create_pool(PRIMARY_DSN, min_size=1, max_size=5)
    standby_pool = await asyncpg.create_pool(STANDBY_DSN, min_size=1, max_size=5)

    # Создаём таблицу заказов (если нет)
    async with primary_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                note TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)


@app.on_event("shutdown")
async def shutdown():
    if primary_pool:
        await primary_pool.close()
    if standby_pool:
        await standby_pool.close()


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.post("/api/orders")
async def create_order():
    """Запись — в primary."""
    note = f"order-{random.randint(1000, 9999)}"
    async with primary_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO orders (note) VALUES ($1) RETURNING id, note, created_at",
            note,
        )
    return JSONResponse({
        "id": row["id"],
        "note": row["note"],
        "created_at": row["created_at"].isoformat(),
        "written_to": "primary",
    })


@app.get("/api/orders")
async def list_orders():
    """Чтение — со standby."""
    async with standby_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, note, created_at FROM orders ORDER BY id DESC LIMIT 20"
        )
    return {
        "read_from": "standby",
        "count": len(rows),
        "items": [
            {
                "id": r["id"],
                "note": r["note"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }


@app.post("/api/load")
async def load(count: int = 100):
    """Налить нагрузку — пачка записей в primary."""
    async with primary_pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO orders (note) VALUES ($1)",
            [(f"load-{random.randint(10000, 99999)}",) for _ in range(count)],
        )
    return {"status": "ok", "inserted": count, "written_to": "primary"}


@app.get("/health")
async def health():
    return {"status": "ok"}


HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Shop app — read/write splitting</title>
  <style>
    body { font-family: sans-serif; max-width: 900px; margin: 30px auto; }
    h1 { font-size: 20px; }
    button { padding: 10px 18px; font-size: 15px; cursor: pointer; margin-right: 10px; }
    table { border-collapse: collapse; width: 100%; margin-top: 20px; font-size: 13px; }
    th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
    th { background: #f0f0f0; }
    .meta { color: #555; font-size: 13px; }
    .tag { padding: 2px 6px; border-radius: 4px; font-size: 11px; color: #fff; }
    .write { background: #2563eb; }
    .read { background: #16a34a; }
  </style>
</head>
<body>
  <h1>Shop app — read/write splitting</h1>
  <p class="meta">
    Запись → <span class="tag write">primary</span>
    · Чтение → <span class="tag read">standby</span>
  </p>

  <div>
    <button onclick="createOrder()">Создать запись</button>
    <button onclick="createLoad()">Налить нагрузку (100)</button>
    <button onclick="refresh()">Обновить список</button>
  </div>
  <p id="status" class="meta"></p>

  <h2 style="font-size:16px; margin-top:30px;">Записи (читаем со standby)</h2>
  <table>
    <thead>
      <tr><th>id</th><th>note</th><th>created_at</th></tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>

<script>
async function createOrder() {
  const r = await fetch('/api/orders', {method: 'POST'});
  const j = await r.json();
  document.getElementById('status').textContent =
    `Создан #${j.id} (записан в primary)`;
  refresh();
}
async function createLoad() {
  document.getElementById('status').textContent = 'Наливаем нагрузку...';
  const r = await fetch('/api/load?count=100', {method: 'POST'});
  const j = await r.json();
  document.getElementById('status').textContent =
    `Налито ${j.inserted} записей (в primary). Проверьте список через 1-2 секунды.`;
  setTimeout(refresh, 500);
}
async function refresh() {
  const r = await fetch('/api/orders');
  const j = await r.json();
  document.getElementById('rows').innerHTML = j.items.map(o =>
    `<tr><td>${o.id}</td><td>${o.note}</td><td>${o.created_at}</td></tr>`
  ).join('');
}
refresh();
</script>
</body>
</html>
"""