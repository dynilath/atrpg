import { useState } from "react";
import Layout from "./components/Layout";
import LandingPage from "./pages/Landing/LandingPage";
import ConsolePage from "./pages/Console/ConsolePage";

type Page = "landing" | "console";

function App() {
  const [page, setPage] = useState<Page>("landing");

  return (
    <Layout currentPage={page} onNavigate={setPage}>
      {page === "landing" && <LandingPage onEnterConsole={() => setPage("console")} />}
      {page === "console" && <ConsolePage />}
    </Layout>
  );
}

export default App;
