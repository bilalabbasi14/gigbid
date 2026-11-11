import express from 'express';
import { ApolloServer } from 'apollo-server-express';
import { typeDefs } from './schema';
import { resolvers } from './resolvers';
import dotenv from 'dotenv';

dotenv.config();

async function start() {
  const app = express();
  const apollo = new ApolloServer({ typeDefs, resolvers });
  await apollo.start();
  apollo.applyMiddleware({ app, path: '/graphql' });

  const port = process.env.PORT || 4000;
  app.listen(port, () => {
    console.log(`🚀 GraphQL server ready at http://localhost:${port}${apollo.graphqlPath}`);
  });
}

start().catch(err => {
  console.error('Failed to start server', err);
  process.exit(1);
});
