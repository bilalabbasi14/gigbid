import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import ArticleViewer from './components/ArticleViewer';
import Home from './components/Home';

const App: React.FC = () => (
  <Router>
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/article/:slug" element={<ArticleViewer />} />
    </Routes>
  </Router>
);

export default App;
