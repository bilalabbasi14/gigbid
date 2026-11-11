import { Pool } from 'pg';

export const pool = new Pool({
  host: process.env.PG_HOST || 'postgres',
  port: 5432,
  user: process.env.PG_USER || 'analytics',
  password: process.env.PG_PASSWORD || 'secret',
  database: process.env.PG_DB || 'analytics_db'
});
