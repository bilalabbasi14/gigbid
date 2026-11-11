import express, { Request, Response } from 'express';
import cors from 'cors';
import { PrismaClient } from '@prisma/client';
import Stripe from 'stripe';
import bodyParser from 'body-parser';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const prisma = new PrismaClient();
const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, { apiVersion: '2022-11-15' });

app.use(cors({ origin: process.env.FRONTEND_URL, credentials: true }));
app.use(bodyParser.json());

// Simple auth middleware placeholder
app.use((req: Request, _res: Response, next) => {
  // In real code verify JWT or session cookie
  next();
});

app.get('/products', async (_req, res) => {
  const products = await prisma.product.findMany();
  res.json(products);
});

app.post('/create-checkout-session', async (req: Request, res: Response) => {
  const { productId, quantity } = req.body;
  const product = await prisma.product.findUnique({ where: { id: Number(productId) } });
  if (!product) return res.status(404).json({ error: 'Product not found' });

  const session = await stripe.checkout.sessions.create({
    payment_method_types: ['card'],
    line_items: [{
      price_data: {
        currency: 'usd',
        product_data: { name: product.name },
        unit_amount: product.priceCents,
      },
      quantity,
    }],
    mode: 'payment',
    success_url: `${process.env.FRONTEND_URL}/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.FRONTEND_URL}/cancel`,
  });
  res.json({ id: session.id });
});

// Stripe webhook for order fulfillment
app.post('/webhook', bodyParser.raw({ type: 'application/json' }), (req, res) => {
  const sig = req.headers['stripe-signature'] as string;
  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch (err) {
    console.log(`⚠️ Webhook signature verification failed.`);
    return res.sendStatus(400);
  }
  if (event.type === 'checkout.session.completed') {
    const session = event.data.object as Stripe.Checkout.Session;
    // Record order in DB (simplified)
    prisma.order.create({
      data: {
        stripeSessionId: session.id,
        amountCents: session.amount_total ?? 0,
        status: 'PAID',
      },
    }).catch(console.error);
  }
  res.json({ received: true });
});

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => console.log(`API listening on port ${PORT}`));
