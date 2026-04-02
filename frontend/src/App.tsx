import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { AuthProvider } from "./context/AuthContext";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter basename={__BASE_PATH__}>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
