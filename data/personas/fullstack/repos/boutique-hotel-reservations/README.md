## Boutique Hotel Reservations (p07)

**Project overview**
The boutique hotel chain approached us in early 2020 needing a fast‑to‑market, server‑less booking engine that could handle real‑time availability, capture payments instantly, and give the small team full control over data without managing their own infrastructure. Over a 9‑week sprint I led a 3‑person team to deliver a Next.js (v13) application that integrates Supabase for authentication and data storage, Stripe Checkout for payment capture, and Tailwind CSS for a responsive UI.

**Architecture**
- **Frontend**: Next.js pages and API routes written in TypeScript. UI components use Tailwind for utility‑first styling and `date-fns` for date handling. The checkout flow is wrapped in a reusable `useStripeCheckout` hook that loads Stripe.js on demand.
- **Backend**: Server‑less functions (`pages/api/*`) act as thin adapters to Supabase (via `@supabase/supabase-js`) and Stripe (`stripe`). All business logic stays in the client bundle, keeping cold‑start latency below 150 ms.
- **Data layer**: Supabase PostgreSQL tables `rooms`, `bookings`, and `users`. Row‑level security policies ensure guests can only read/write their own bookings.
- **Payments**: Stripe Checkout session is created server‑side; the client redirects to Stripe and receives a webhook (handled by a Next.js API route) that marks the booking as `paid`.

**Key implementation details**
- Availability is calculated on the fly using a SQL view that aggregates existing bookings; the view is queried via Supabase's `rpc` function to keep the client lightweight.
- The booking form validates date ranges with `date-fns` and disables dates that are already booked.
- Environment variables (`NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`) are loaded through Vercel's dashboard for secure deployment.

**Results**
- Occupancy jumped from **62 % to 78 %** within six months of launch.
- After the Stripe integration, payment failures dropped to **0 %**.
- The client can now manage rooms and bookings directly in Supabase Studio without developer intervention.

**Running the project**
```bash
# clone the repo
git clone https://github.com/example/boutique-hotel-reservations.git
cd boutique-hotel-reservations

# install deps
npm ci

# set env vars (copy .env.example first)
cp .env.example .env.local
# edit .env.local with your Supabase and Stripe keys

# start dev server
npm run dev
```
The app will be available at `http://localhost:3000`. The Stripe webhook endpoint can be tested with `stripe listen --forward-to localhost:3000/api/webhook/stripe`.

---
*Lead Engineer: Daniel Okafor*
