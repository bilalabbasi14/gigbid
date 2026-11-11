import type { NextApiRequest, NextApiResponse } from 'next';
import { prisma } from '../../lib/prisma';
import { z } from 'zod';
import { parse } from 'querystring';

const ListingSchema = z.object({
  title: z.string().min(5),
  price: z.number().positive(),
  city: z.string(),
  state: z.string().length(2),
  description: z.string().optional(),
  isActive: z.boolean().default(true),
});

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method === 'GET') {
    const listings = await prisma.listing.findMany({ where: { isActive: true } });
    return res.status(200).json(listings);
  }
  if (req.method === 'POST') {
    try {
      const data = ListingSchema.parse(req.body);
      const newListing = await prisma.listing.create({ data });
      return res.status(201).json(newListing);
    } catch (e) {
      return res.status(400).json({ error: 'Invalid payload', details: e instanceof Error ? e.message : e });
    }
  }
  res.setHeader('Allow', ['GET', 'POST']);
  res.status(405).end(`Method ${req.method} Not Allowed`);
}
