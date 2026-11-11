import React from 'react';
import { ApolloClient, InMemoryCache, ApolloProvider, HttpLink } from '@apollo/client';
import Board from './Board';

const client = new ApolloClient({
  link: new HttpLink({ uri: 'http://localhost:4000/graphql' }),
  cache: new InMemoryCache({
    typePolicies: {
      Query: {
        fields: {
          tasks: {
            merge: true,
          },
        },
      },
    },
  }),
});

const App: React.FC = () => (
  <ApolloProvider client={client}>
    <div style={{ padding: '20px' }}>
      <h1>Audit Workflow Kanban</h1>
      <Board />
    </div>
  </ApolloProvider>
);

export default App;
