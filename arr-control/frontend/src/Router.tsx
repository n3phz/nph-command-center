import { BrowserRouter, Routes, Route } from 'react-router-dom';
import App from './App';
import ItemDetailPage from './pages/ItemDetail';

function Router() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/item/:id" element={<ItemDetailPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default Router;