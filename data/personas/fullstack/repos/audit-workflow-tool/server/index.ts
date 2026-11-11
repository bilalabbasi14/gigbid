import express from 'express';
import { ApolloServer } from 'apollo-server-express';
import { typeDefs } from './schema';
import { resolvers } from './resolvers';
import cors from 'cors';
import { Pool } from 'pg';

const app = express();
app.use(cors({ origin: 'http://localhost:3000', credentials: true }));

const pool = new Pool({
  user: 'audit_user',
  host: 'postgres',
  database: 'audit_db',
  password: 'securepass',
  port: 5432,
});

const server = new ApolloServer({
  typeDefs,
  resolvers,
  context: () => ({ pool }),
});

(async () => {
  await server.start();
  server.applyMiddleware({ app, path: '/graphql' });
  const PORT = process.env.PORT || 4000;
  app.listen(PORT, () => console.log(`🚀 Server ready at http://localhost:${PORT}${server.graphqlPath}`));
})();
