import { Navigate, Route, Routes } from "react-router-dom";
import { getStoredUser, getToken } from "./api/client";
import { Toaster } from "./components/Toaster";
import { Account } from "./pages/Account";
import { Alertas } from "./pages/Alertas";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { ServerDetail } from "./pages/ServerDetail";
import { Servidores } from "./pages/Servidores";
import { Settings } from "./pages/Settings";

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

function RequireOperator({ children }: { children: React.ReactNode }) {
  if (getStoredUser()?.role === "viewer") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
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
        path="/servers"
        element={
          <Protected>
            <Servidores />
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
      <Route
        path="/alerts"
        element={
          <Protected>
            <Alertas />
          </Protected>
        }
      />
      <Route
        path="/settings"
        element={
          <Protected>
            <RequireOperator>
              <Settings />
            </RequireOperator>
          </Protected>
        }
      />
      <Route
        path="/account"
        element={
          <Protected>
            <Account />
          </Protected>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
