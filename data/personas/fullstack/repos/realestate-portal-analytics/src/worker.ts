import { createRedisClient } from './redisClient';
import { pool } from './pgPool';
import { Redis } from 'ioredis';

const redis: Redis = createRedisClient();

async function processStream() {
  let lastId = '$';
  while (true) {
    const streams = await redis.xread('BLOCK', 5000, 'STREAMS', 'events:raw', lastId);
    if (!streams) continue;
    const [[, entries]] = streams;
    for (const [id, fields] of entries) {
      const data: any = {};
      for (let i = 0; i < fields.length; i += 2) data[fields[i]] = fields[i + 1];
      const { listingId, eventType } = data;
      const hashKey = `stats:listing:${listingId}`;
      if (eventType === 'view') await redis.hincrby(hashKey, 'views', 1);
      else if (eventType === 'click') await redis.hincrby(hashKey, 'clicks', 1);
      lastId = id;
    }
  }
}

// Periodic flush to PostgreSQL (once a day in production; here every minute for demo)
setInterval(async () => {
  const keys = await redis.keys('stats:listing:*');
  for (const key of keys) {
    const listingId = key.split(':')[2];
    const stats = await redis.hgetall(key);
    await pool.query(
      `INSERT INTO listing_daily_stats (listing_id, day, views, clicks)
       VALUES ($1, CURRENT_DATE, $2, $3)
       ON CONFLICT (listing_id, day) DO UPDATE SET views = EXCLUDED.views, clicks = EXCLUDED.clicks;`,
      [listingId, parseInt(stats.views ?? '0'), parseInt(stats.clicks ?? '0')]
    );
    await redis.del(key);
  }
}, 60_000);

processStream().catch(console.error);
