import Redis from 'ioredis';

export function createRedisClient() {
  return new Redis({ host: process.env.REDIS_HOST || 'redis', port: 6379 });
}
