import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import LandingPage from "./pages/Landing/LandingPage";
import ConsolePage from "./pages/Console/ConsolePage";
import PlayerPageWrapper from "./pages/Player/PlayerPageWrapper";

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/console" element={<ConsolePage />} />
          <Route path="/player" element={<PlayerPageWrapper />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
