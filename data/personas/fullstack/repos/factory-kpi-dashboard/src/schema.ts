import { gql } from 'apollo-server-express';

export const typeDefs = gql`
  type EquipmentKPI {
    equipmentId: ID!
    timestamp: String!
    efficiency: Float!
    uptime: Float!
    downtime: Float!
  }

  type Query {
    kpis(equipmentId: ID!, from: String!, to: String!): [EquipmentKPI!]!
    latestKPI(equipmentId: ID!): EquipmentKPI
  }
`;
