import type { NextApiRequest, NextApiResponse } from 'next';
import Stripe from 'stripe';
import { supabase } from '../../utils/supabaseClient';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2023-08-16',
});

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).end('Method Not Allowed');
  }

  const { roomId, startDate, endDate, userId } = req.body;
  // Verify room availability via Supabase RPC
  const { data: available, error } = await supabase
    .rpc('check_room_availability', { room_id: roomId, start_date: startDate, end_date: endDate });
  if (error || !available) {
    return res.status(400).json({ message: 'Room not available for selected dates.' });
  }

  // Create a Stripe Checkout session
  const session = await stripe.checkout.sessions.create({
    payment_method_types: ['card'],
    mode: 'payment',
    line_items: [{
      price_data: {
        currency: 'usd',
        product_data: { name: `Room ${roomId} booking` },
        unit_amount: 12000, // $120 per night, placeholder
      },
      quantity: Math.ceil((new Date(endDate).getTime() - new Date(startDate).getTime()) / (1000 * 60 * 60 * 24)),
    }],
    metadata: { roomId: String(roomId), userId, startDate, endDate },
    success_url: `${process.env.NEXT_PUBLIC_BASE_URL}/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.NEXT_PUBLIC_BASE_URL}/rooms/${roomId}`,
  });

  // Store a pending booking record
  await supabase.from('bookings').insert({
    room_id: roomId,
    user_id: userId,
    start_date: startDate,
    end_date: endDate,
    stripe_session_id: session.id,
    status: 'pending',
  });

  res.status(200).json({ id: session.id });
}
