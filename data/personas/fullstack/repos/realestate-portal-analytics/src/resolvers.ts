import { IResolvers } from '@graphql-tools/utils';
import { Query } from '../schema';

export const resolvers: IResolvers = {
  Query: {
    async listingStats(_: any, args: { listingId: string }, context: any) {
      const { listingId } = args;
      const { redis, pg } = context;
      // Try hot data first
      const hot = await redis.hgetall(`stats:listing:${listingId}`);
      if (Object.keys(hot).length) {
        return {
          listingId,
          views: parseInt(hot.views ?? '0'),
          clicks: parseInt(hot.clicks ?? '0'),
          source: 'redis'
        };
      }
      // Fallback to daily aggregate
      const { rows } = await pg.query(
        'SELECT views, clicks FROM listing_daily_stats WHERE listing_id = $1 ORDER BY day DESC LIMIT 1',
        [listingId]
      );
      const latest = rows[0] || { views: 0, clicks: 0 };
      return { listingId, views: latest.views, clicks: latest.clicks, source: 'postgres' };
    }
  }
};
