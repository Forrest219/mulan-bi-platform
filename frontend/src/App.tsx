import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { AuthProvider } from "./context/AuthContext";
import { PlatformSettingsProvider } from "./context/PlatformSettingsContext";

function App() {
  return (
    <AuthProvider>
      <PlatformSettingsProvider>
        <BrowserRouter basename={__BASE_PATH__}>
          <AppRoutes />
        </BrowserRouter>
      </PlatformSettingsProvider>
    </AuthProvider>
  );
}

export default App;
