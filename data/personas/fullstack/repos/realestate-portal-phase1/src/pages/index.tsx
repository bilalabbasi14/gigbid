import type { GetServerSideProps, NextPage } from 'next';
import Head from 'next/head';
import { NextSeo } from 'next-seo';
import { prisma } from '../lib/prisma';
import ListingCard from '../components/ListingCard';
import type { Listing } from '@prisma/client';

interface HomeProps {
  listings: Listing[];
}

export const getServerSideProps: GetServerSideProps = async () => {
  const listings = await prisma.listing.findMany({
    where: { isActive: true },
    orderBy: { createdAt: 'desc' },
    include: { images: { take: 1 } },
    take: 12,
  });
  return { props: { listings } };
};

const Home: NextPage<HomeProps> = ({ listings }) => {
  return (
    <>
      <NextSeo
        title="Rental & Sales Listings – Your City"
        description="Browse the latest rental and sale properties from our agency. Updated daily."
        openGraph={{ url: process.env.NEXT_PUBLIC_BASE_URL, title: 'Property Listings', images: [{ url: '/og-image.png' }] }}
      />
      <Head>
        <title>Property Listings Portal</title>
      </Head>
      <main className="max-w-7xl mx-auto p-4 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {listings.map((listing) => (
          <ListingCard key={listing.id} listing={listing} />
        ))}
      </main>
    </>
  );
};

export default Home;
