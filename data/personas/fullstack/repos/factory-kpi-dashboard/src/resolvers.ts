import { Pool } from 'pg';
import { IResolvers } from '@graphql-tools/utils';

// PostgreSQL connection pool – credentials match docker-compose.yml
const pool = new Pool({
  host: process.env.PGHOST || 'db',
  port: Number(process.env.PGPORT) || 5432,
  user: process.env.PGUSER || 'kpi_user',
  password: process.env.PGPASSWORD || 'kpi_pass',
  database: process.env.PGDATABASE || 'kpi_db',
});

export const resolvers: IResolvers = {
  Query: {
    async kpis(_, { equipmentId, from, to }) {
      const sql = `
        SELECT equipment_id, ts, efficiency, uptime, downtime
        FROM equipment_kpis
        WHERE equipment_id = $1 AND ts BETWEEN $2 AND $3
        ORDER BY ts ASC`;
      const { rows } = await pool.query(sql, [equipmentId, from, to]);
      return rows.map(r => ({
        equipmentId: r.equipment_id,
        timestamp: r.ts.toISOString(),
        efficiency: Number(r.efficiency),
        uptime: Number(r.uptime),
        downtime: Number(r.downtime),
      }));
    },
    async latestKPI(_, { equipmentId }) {
      const sql = `
        SELECT equipment_id, ts, efficiency, uptime, downtime
        FROM equipment_kpis
        WHERE equipment_id = $1
        ORDER BY ts DESC
        LIMIT 1`;
      const { rows } = await pool.query(sql, [equipmentId]);
      const r = rows[0];
      if (!r) return null;
      return {
        equipmentId: r.equipment_id,
        timestamp: r.ts.toISOString(),
        efficiency: Number(r.efficiency),
        uptime: Number(r.uptime),
        downtime: Number(r.downtime),
      };
    },
  },
};
