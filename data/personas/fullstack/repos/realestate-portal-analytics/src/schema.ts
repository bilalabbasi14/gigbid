import { gql } from 'apollo-server-express';

export const typeDefs = gql`
  type ListingStats {
    listingId: ID!
    views: Int!
    clicks: Int!
    source: String!
  }

  type Query {
    listingStats(listingId: ID!): ListingStats!
  }
`;
