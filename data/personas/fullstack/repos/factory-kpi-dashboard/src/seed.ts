import { Pool } from 'pg';
import { randomInt, randomFloat } from 'crypto';

const pool = new Pool({
  host: process.env.PGHOST || 'db',
  port: Number(process.env.PGPORT) || 5432,
  user: process.env.PGUSER || 'kpi_user',
  password: process.env.PGPASSWORD || 'kpi_pass',
  database: process.env.PGDATABASE || 'kpi_db',
});

async function createTables() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS equipment_kpis (
      id SERIAL PRIMARY KEY,
      equipment_id VARCHAR(50) NOT NULL,
      ts TIMESTAMPTZ NOT NULL,
      efficiency NUMERIC(5,2),
      uptime NUMERIC(5,2),
      downtime NUMERIC(5,2)
    );
  `);
}

async function generateData() {
  const equipmentIds = ['EQ-1001', 'EQ-1002', 'EQ-1003'];
  const now = Date.now();
  const rows: string[] = [];
  for (let i = 0; i < 10000; i++) {
    const eq = equipmentIds[randomInt(0, equipmentIds.length)];
    const ts = new Date(now - randomInt(0, 30 * 24 * 60 * 60 * 1000)); // last 30 days
    const eff = (randomFloat() * 100).toFixed(2);
    const up = (randomFloat() * 8).toFixed(2);
    const down = (8 - Number(up)).toFixed(2);
    rows.push(`('${eq}', '${ts.toISOString()}', ${eff}, ${up}, ${down})`);
  }
  const sql = `INSERT INTO equipment_kpis (equipment_id, ts, efficiency, uptime, downtime) VALUES ${rows.join(',')}`;
  await pool.query(sql);
}

async function main() {
  await createTables();
  await generateData();
  console.log('Seed data inserted');
  await pool.end();
}

main().catch(err => console.error(err));
