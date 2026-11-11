import express from 'express';
import { ApolloServer } from 'apollo-server-express';
import { typeDefs } from './schema';
import { resolvers } from './resolvers';
import { createRedisClient } from './redisClient';
import { pool } from './pgPool';
import bodyParser from 'body-parser';

const app = express();
app.use(bodyParser.json());

// Simple event ingestion endpoint
app.post('/events', async (req, res) => {
  const { listingId, eventType, timestamp } = req.body;
  if (!listingId || !eventType) return res.status(400).send('Invalid payload');
  const client = createRedisClient();
  await client.xadd('events:raw', '*', 'listingId', listingId, 'eventType', eventType, 'ts', timestamp ?? Date.now().toString());
  res.status(202).send('Accepted');
});

const server = new ApolloServer({ typeDefs, resolvers, context: { pg: pool, redis: createRedisClient() } });
(async () => {
  await server.start();
  server.applyMiddleware({ app, path: '/graphql' });
  const port = process.env.PORT || 4000;
  app.listen(port, () => console.log(`🚀 Analytics service listening on http://localhost:${port}${server.graphqlPath}`));
})();
