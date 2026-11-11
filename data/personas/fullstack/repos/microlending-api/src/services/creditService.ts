import Redis from 'ioredis';
import axios from 'axios';

const redis = new Redis(process.env.REDIS_URL!);

export async function getCreditScore(userId: string): Promise<number> {
  const cacheKey = `creditScore:${userId}`;
  const cached = await redis.get(cacheKey);
  if (cached) {
    return Number(cached);
  }
  // Simulate external credit‑score provider
  const response = await axios.get(`https://api.creditscore.io/users/${userId}`);
  const score = response.data.score as number;
  // Cache for 10 minutes
  await redis.setex(cacheKey, 600, score.toString());
  return score;
}
