import { gql } from 'apollo-server-express';

export const typeDefs = gql`
  type Task {
    id: ID!
    title: String!
    columnId: ID!
    assigneeId: ID
  }

  type Column {
    id: ID!
    name: String!
  }

  type Query {
    tasks: [Task!]!
    columns: [Column!]!
  }

  type Mutation {
    moveTask(taskId: ID!, columnId: ID!): Task!
  }
`;
