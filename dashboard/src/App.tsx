import { Navigate, Route, Routes } from "react-router-dom";
import { getToken } from "./api/client";
import { Toaster } from "./components/Toaster";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { ServerDetail } from "./pages/ServerDetail";

function Protected({ children }: { children: React.ReactNode }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  // Toaster acompanha toda a área autenticada (pop-up + Notification do SO)
  return (
    <>
      {children}
      <Toaster />
    </>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Protected>
            <Overview />
          </Protected>
        }
      />
      <Route
        path="/servers/:id"
        element={
          <Protected>
            <ServerDetail />
          </Protected>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
