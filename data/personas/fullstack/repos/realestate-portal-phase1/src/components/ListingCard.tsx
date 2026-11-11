import Image from 'next/image';
import Link from 'next/link';
import type { Listing } from '@prisma/client';

interface Props {
  listing: Listing & { images: { url: string }[] };
}

export default function ListingCard({ listing }: Props) {
  const thumbnail = listing.images[0]?.url || '/placeholder.png';
  return (
    <div className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow">
      <Link href={`/listings/${listing.id}`}> 
        <a className="block">
          <Image src={thumbnail} alt={listing.title} width={400} height={250} className="rounded-t-lg" />
          <div className="p-4">
            <h3 className="text-lg font-semibold truncate">{listing.title}</h3>
            <p className="text-sm text-gray-600">{listing.city}, {listing.state}</p>
            <p className="mt-2 text-primary-600 font-bold">${listing.price.toLocaleString()}</p>
          </div>
        </a>
      </Link>
    </div>
  );
}
