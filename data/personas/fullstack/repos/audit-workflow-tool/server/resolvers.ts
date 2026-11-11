export const resolvers = {
  Query: {
    tasks: async (_: any, __: any, { pool }: any) => {
      const res = await pool.query('SELECT id, title, column_id FROM tasks');
      return res.rows.map((row: any) => ({
        id: row.id,
        title: row.title,
        columnId: row.column_id,
      }));
    },
    columns: async (_: any, __: any, { pool }: any) => {
      const res = await pool.query('SELECT id, name FROM columns');
      return res.rows;
    },
  },
  Mutation: {
    moveTask: async (_: any, { taskId, columnId }: any, { pool }: any) => {
      await pool.query('UPDATE tasks SET column_id = $1 WHERE id = $2', [columnId, taskId]);
      const res = await pool.query('SELECT id, title, column_id FROM tasks WHERE id = $1', [taskId]);
      const row = res.rows[0];
      return { id: row.id, title: row.title, columnId: row.column_id };
    },
  },
};
