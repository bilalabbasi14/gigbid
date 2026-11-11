import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import axios from 'axios';

type Article = {
  title: string;
  author: string;
  content: string;
  published_at: string;
};

const ArticleViewer: React.FC = () => {
  const { slug } = useParams<{ slug: string }>();
  const [article, setArticle] = useState<Article | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchArticle = async () => {
      try {
        const res = await axios.get(`/api/articles/?slug=${slug}`);
        if (res.data.length) setArticle(res.data[0]);
      } catch (err) {
        console.error('Error fetching article', err);
      } finally {
        setLoading(false);
      }
    };
    fetchArticle();
  }, [slug]);

  if (loading) return <p>Loading...</p>;
  if (!article) return <p>Article not found.</p>;

  return (
    <article>
      <h1>{article.title}</h1>
      <p><em>By {article.author} on {new Date(article.published_at).toLocaleDateString()}</em></p>
      <ReactMarkdown>{article.content}</ReactMarkdown>
    </article>
  );
};

export default ArticleViewer;
