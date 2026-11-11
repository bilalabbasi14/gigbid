import { createClient } from '@supabase/supabase-js';

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// Helper to fetch room availability for a date range
export async function getAvailableRooms(start: string, end: string) {
  const { data, error } = await supabase
    .rpc('available_rooms', { start_date: start, end_date: end });
  if (error) throw error;
  return data;
}
