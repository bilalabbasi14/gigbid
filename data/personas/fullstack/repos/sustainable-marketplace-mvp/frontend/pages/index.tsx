import type { NextPage } from 'next';
import { useQuery } from 'react-query';
import axios from 'axios';
import Link from 'next/link';

interface Product {
  id: number;
  name: string;
  priceCents: number;
  imageUrl: string;
}

const fetchProducts = async (): Promise<Product[]> => {
  const { data } = await axios.get(`${process.env.NEXT_PUBLIC_API_URL}/products`);
  return data;
};

const Home: NextPage = () => {
  const { data, isLoading, error } = useQuery('products', fetchProducts);

  if (isLoading) return <p className="text-center mt-8">Loading products…</p>;
  if (error) return <p className="text-red-600">Failed to load.</p>;

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-3xl font-bold mb-6">Eco‑Friendly Marketplace</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {data!.map((p) => (
          <div key={p.id} className="border rounded-lg p-4 shadow">
            <img src={p.imageUrl} alt={p.name} className="w-full h-48 object-cover mb-2" />
            <h2 className="text-xl font-semibold">{p.name}</h2>
            <p className="text-lg text-green-600">${(p.priceCents / 100).toFixed(2)}</p>
            <Link href={`/checkout/${p.id}`}>
              <a className="mt-2 inline-block bg-green-500 text-white px-4 py-2 rounded">Buy</a>
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
};

export default Home;
