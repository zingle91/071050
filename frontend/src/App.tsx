import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import LoginPage from "./pages/LoginPage";
import MessengerPage from "./pages/MessengerPage";
import NoteDetailPage from "./pages/NoteDetailPage";

function Private({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center">로딩 중...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/notes/:id"
        element={
          <Private>
            <NoteDetailPage />
          </Private>
        }
      />
      <Route
        path="/*"
        element={
          <Private>
            <MessengerPage />
          </Private>
        }
      />
    </Routes>
  );
}